const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


class FakeElement {
    constructor() {
        this.children = [];
        this.disabled = false;
        this.textContent = "";
        this.value = "";
    }

    appendChild(child) {
        this.children.push(child);
    }

    replaceChildren() {
        this.children = [];
    }
}


function jsonResponse(status, body) {
    return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
    };
}


function nonJsonResponse(status) {
    return {
        ok: false,
        status,
        json: async () => {
            throw new SyntaxError("Unexpected token '<'");
        },
    };
}


function deferred() {
    let resolve;
    const promise = new Promise((resolvePromise) => {
        resolve = resolvePromise;
    });
    return {promise, resolve};
}


function loadCollectionPage(fetchImpl) {
    const elements = new Map([
        ["task-status", new FakeElement()],
        ["success-count", new FakeElement()],
        ["task-keyword", new FakeElement()],
        ["task-target-count", new FakeElement()],
        ["task-existing-count", new FakeElement()],
        ["task-added-count", new FakeElement()],
        ["task-total-count", new FakeElement()],
        ["task-course-target", new FakeElement()],
        ["task-course-progress", new FakeElement()],
        ["task-message", new FakeElement()],
        ["poll-error", new FakeElement()],
        ["latest-videos-note", new FakeElement()],
        ["latest-videos", new FakeElement()],
        ["clean-status", new FakeElement()],
        ["clean-before", new FakeElement()],
        ["clean-after", new FakeElement()],
        ["clean-removed", new FakeElement()],
        ["clean-result-date", new FakeElement()],
        ["clean-message", new FakeElement()],
    ]);
    const collectDate = new FakeElement();
    collectDate.value = "2026-08-09";
    let collectDateChangeHandler;
    collectDate.addEventListener = (eventName, handler) => {
        assert.equal(eventName, "change");
        collectDateChangeHandler = handler;
    };
    elements.set("collect-date", collectDate);
    const fakeForm = new FakeElement();
    fakeForm.elements = {
        keyword: {value: "大数据技术"},
        date: collectDate,
        target_count: {value: "1"},
    };
    let collectSubmitHandler;
    fakeForm.addEventListener = (eventName, handler) => {
        assert.equal(eventName, "submit");
        collectSubmitHandler = handler;
    };
    elements.set("collect-form", fakeForm);

    const cleanDate = new FakeElement();
    cleanDate.value = "2026-08-09";
    elements.set("clean-date", cleanDate);
    const cleanForm = new FakeElement();
    cleanForm.elements = {date: cleanDate};
    let cleanSubmitHandler;
    cleanForm.addEventListener = (eventName, handler) => {
        assert.equal(eventName, "submit");
        cleanSubmitHandler = handler;
    };
    elements.set("clean-form", cleanForm);

    let nextTimerId = 1;
    const timers = new Map();
    const clearedTimers = [];
    const location = {href: ""};
    const context = {
        clearInterval(timerId) {
            clearedTimers.push(timerId);
            timers.delete(timerId);
        },
        document: {
            createElement: () => new FakeElement(),
            getElementById: (id) => elements.get(id),
        },
        fetch: fetchImpl,
        location,
        setInterval(callback, delay) {
            const timerId = nextTimerId;
            nextTimerId += 1;
            timers.set(timerId, {callback, delay});
            return timerId;
        },
    };
    vm.createContext(context);
    const scriptPath = path.join(__dirname, "..", "static", "js", "main.js");
    vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);

    return {
        clearedTimers,
        clean: () => cleanSubmitHandler({preventDefault() {}}),
        changeCollectDate: () => collectDateChangeHandler(),
        elements,
        submit: () => collectSubmitHandler({preventDefault() {}}),
        timers,
        location,
    };
}


test("changing collection date reloads the server-rendered page without API calls", () => {
    let requestCount = 0;
    const page = loadCollectionPage(async () => {
        requestCount += 1;
        throw new Error("date change must not call fetch");
    });

    page.elements.get("collect-date").value = "2026-08-13";
    page.changeCollectDate();

    assert.equal(page.location.href, "/collect?date=2026-08-13");
    assert.equal(requestCount, 0);
});


test("terminal status renders existing added total and course progress", async () => {
    const page = loadCollectionPage(async (url) => {
        if (url === "/api/collect") {
            return jsonResponse(202, {task_id: 41});
        }
        return jsonResponse(200, {
            id: 41,
            keyword: "Flink CDC",
            target_count: 500,
            success_count: 300,
            status: "success",
            message: "目标新增500条，实际新增300条",
            existing_count: 8000,
            added_count: 300,
            total_count: 8300,
            course_target: 10000,
            latest_videos: [],
            latest_videos_note: "该日期最新原始采集数据（最多10条）",
        });
    });

    await page.submit();

    assert.equal(page.elements.get("task-keyword").textContent, "Flink CDC");
    assert.equal(page.elements.get("task-target-count").textContent, 500);
    assert.equal(page.elements.get("task-existing-count").textContent, 8000);
    assert.equal(page.elements.get("task-added-count").textContent, 300);
    assert.equal(page.elements.get("task-total-count").textContent, 8300);
    assert.equal(page.elements.get("task-course-target").textContent, 10000);
    assert.equal(page.elements.get("task-course-progress").textContent, "83.00%");
});


test("status without an initialized HDFS snapshot renders unknown counts", async () => {
    const page = loadCollectionPage(async (url) => {
        if (url === "/api/collect") {
            return jsonResponse(202, {task_id: 41});
        }
        return jsonResponse(200, {
            id: 41,
            keyword: "Spark",
            target_count: 20,
            success_count: 0,
            status: "waiting",
            message: "",
            existing_count: null,
            added_count: 0,
            total_count: null,
            course_target: 10000,
            latest_videos: [],
            latest_videos_note: "",
        });
    });

    await page.submit();

    assert.equal(page.elements.get("task-existing-count").textContent, "--");
    assert.equal(page.elements.get("task-added-count").textContent, 0);
    assert.equal(page.elements.get("task-total-count").textContent, "--");
    assert.equal(page.elements.get("task-course-progress").textContent, "--");
});


test("manual cleaning posts the date and renders returned counts", async () => {
    const requests = [];
    const page = loadCollectionPage(async (url, options) => {
        requests.push({url, options});
        return jsonResponse(200, {
            before_count: 100,
            after_count: 96,
            removed_count: 4,
            message: "数据清洗完成",
        });
    });

    await page.clean();

    assert.equal(requests[0].url, "/api/clean");
    assert.deepEqual(JSON.parse(requests[0].options.body), {date: "2026-08-09"});
    assert.equal(page.elements.get("clean-status").textContent, "清洗完成");
    assert.equal(page.elements.get("clean-before").textContent, "100");
    assert.equal(page.elements.get("clean-after").textContent, "96");
    assert.equal(page.elements.get("clean-removed").textContent, "4");
    assert.equal(page.elements.get("clean-result-date").textContent, "2026-08-09");
});


test("a failed cleaning submission clears counts and reports a non-JSON server failure", async () => {
    let requestCount = 0;
    const page = loadCollectionPage(async () => {
        requestCount += 1;
        if (requestCount === 1) {
            return jsonResponse(200, {
                before_count: 10,
                after_count: 8,
                removed_count: 2,
                message: "数据清洗完成",
            });
        }
        return nonJsonResponse(500);
    });

    await page.clean();
    await page.clean();

    assert.equal(page.elements.get("clean-before").textContent, "--");
    assert.equal(page.elements.get("clean-after").textContent, "--");
    assert.equal(page.elements.get("clean-removed").textContent, "--");
    assert.equal(page.elements.get("clean-status").textContent, "清洗失败");
    assert.equal(
        page.elements.get("clean-message").textContent,
        "请求失败：500，服务器返回了非 JSON 响应",
    );
});


test("a stale cleaning response cannot overwrite the active date or result", async () => {
    const firstSubmission = deferred();
    const secondSubmission = deferred();
    let requestCount = 0;
    const page = loadCollectionPage(async () => {
        requestCount += 1;
        return requestCount === 1 ? firstSubmission.promise : secondSubmission.promise;
    });

    page.elements.get("clean-date").value = "2026-08-08";
    const olderRequest = page.clean();
    page.elements.get("clean-date").value = "2026-08-09";
    const activeRequest = page.clean();

    secondSubmission.resolve(jsonResponse(200, {
        before_count: 20,
        after_count: 18,
        removed_count: 2,
        message: "新日期清洗完成",
    }));
    await activeRequest;
    firstSubmission.resolve(jsonResponse(200, {
        before_count: 100,
        after_count: 90,
        removed_count: 10,
        message: "旧日期清洗完成",
    }));
    await olderRequest;

    assert.equal(page.elements.get("clean-result-date").textContent, "2026-08-09");
    assert.equal(page.elements.get("clean-before").textContent, "20");
    assert.equal(page.elements.get("clean-after").textContent, "18");
    assert.equal(page.elements.get("clean-removed").textContent, "2");
    assert.equal(page.elements.get("clean-message").textContent, "新日期清洗完成");
});


test("an older submission response cannot replace the newer task", async () => {
    const firstSubmission = deferred();
    const secondSubmission = deferred();
    let submissionCount = 0;
    const statusRequests = [];
    const page = loadCollectionPage(async (url) => {
        if (url === "/api/collect") {
            submissionCount += 1;
            return submissionCount === 1
                ? firstSubmission.promise
                : secondSubmission.promise;
        }
        statusRequests.push(url);
        const taskId = Number(url.split("/").at(-1));
        return jsonResponse(200, {
            id: taskId,
            status: taskId === 41 ? "success" : "running",
            success_count: taskId === 41 ? 1 : 0,
            message: taskId === 41 ? "旧任务完成" : "新任务运行中",
            latest_videos: [],
            latest_videos_note: "",
        });
    });

    const olderRequest = page.submit();
    const newerRequest = page.submit();
    secondSubmission.resolve(jsonResponse(202, {task_id: 42}));
    await newerRequest;
    const newerTimerId = [...page.timers.keys()][0];

    firstSubmission.resolve(jsonResponse(202, {task_id: 41}));
    await olderRequest;

    assert.deepEqual(statusRequests, ["/api/collect/status/42"]);
    assert.equal(page.elements.get("task-status").textContent, "running");
    assert.equal(page.elements.get("task-message").textContent, "新任务运行中");
    assert.equal(page.clearedTimers.includes(newerTimerId), false);
});


test("a stale terminal poll cannot overwrite or stop the newer task", async () => {
    const staleStatus = deferred();
    let submissionCount = 0;
    let task41StatusCount = 0;
    const page = loadCollectionPage(async (url) => {
        if (url === "/api/collect") {
            submissionCount += 1;
            return jsonResponse(202, {task_id: submissionCount === 1 ? 41 : 42});
        }
        if (url === "/api/collect/status/41") {
            task41StatusCount += 1;
            if (task41StatusCount === 2) {
                return staleStatus.promise;
            }
            return jsonResponse(200, {
                id: 41,
                status: "running",
                success_count: 0,
                message: "旧任务运行中",
                latest_videos: [],
                latest_videos_note: "",
            });
        }
        return jsonResponse(200, {
            id: 42,
            status: "running",
            success_count: 0,
            message: "新任务运行中",
            latest_videos: [],
            latest_videos_note: "",
        });
    });

    await page.submit();
    const oldTimer = [...page.timers.values()][0];
    const oldPoll = oldTimer.callback();
    await page.submit();
    const newerTimerId = [...page.timers.keys()][0];

    staleStatus.resolve(jsonResponse(200, {
        id: 41,
        status: "success",
        success_count: 1,
        message: "旧任务完成",
        latest_videos: [],
        latest_videos_note: "旧任务数据",
    }));
    await oldPoll;

    assert.equal(page.elements.get("task-status").textContent, "running");
    assert.equal(page.elements.get("task-message").textContent, "新任务运行中");
    assert.equal(page.clearedTimers.includes(newerTimerId), false);
});


test("overlapping status intervals issue only one request at a time", async () => {
    const delayedStatus = deferred();
    let statusRequestCount = 0;
    const page = loadCollectionPage(async (url) => {
        if (url === "/api/collect") {
            return jsonResponse(202, {task_id: 41});
        }
        statusRequestCount += 1;
        if (statusRequestCount === 1) {
            return jsonResponse(200, {
                id: 41,
                status: "running",
                success_count: 0,
                message: "运行中",
                latest_videos: [],
                latest_videos_note: "",
            });
        }
        return delayedStatus.promise;
    });

    await page.submit();
    const timer = [...page.timers.values()][0];
    const firstPoll = timer.callback();
    const overlappingPoll = timer.callback();

    assert.equal(statusRequestCount, 2);
    delayedStatus.resolve(jsonResponse(200, {
        id: 41,
        status: "running",
        success_count: 0,
        message: "仍在运行",
        latest_videos: [],
        latest_videos_note: "",
    }));
    await Promise.all([firstPoll, overlappingPoll]);
});


test("a transient status error keeps polling until the server reports a terminal state", async () => {
    let statusAttempts = 0;
    const page = loadCollectionPage(async (url) => {
        if (url === "/api/collect") {
            return jsonResponse(202, {task_id: 41});
        }

        assert.equal(url, "/api/collect/status/41");
        statusAttempts += 1;
        if (statusAttempts === 1) {
            throw new Error("临时无法读取状态");
        }
        if (statusAttempts === 2) {
            return jsonResponse(200, {
                id: 41,
                status: "running",
                success_count: 0,
                message: "正在采集",
                latest_videos: [],
                latest_videos_note: "",
            });
        }
        return jsonResponse(200, {
            id: 41,
            status: "success",
            success_count: 1,
            message: "采集完成",
            latest_videos: [],
            latest_videos_note: "该日期最新部分数据",
        });
    });

    await page.submit();
    const [timerId, timer] = [...page.timers.entries()][0];

    assert.equal(page.elements.get("task-status").textContent, "waiting");
    assert.equal(
        page.elements.get("poll-error").textContent,
        "状态更新失败：临时无法读取状态",
    );
    assert.equal(timer.delay, 2000);
    assert.equal(page.clearedTimers.includes(timerId), false);

    await timer.callback();

    assert.equal(page.elements.get("task-status").textContent, "running");
    assert.equal(page.elements.get("poll-error").textContent, "");
    assert.equal(page.clearedTimers.includes(timerId), false);

    await timer.callback();

    assert.equal(page.elements.get("task-status").textContent, "success");
    assert.equal(page.clearedTimers.includes(timerId), true);
});
