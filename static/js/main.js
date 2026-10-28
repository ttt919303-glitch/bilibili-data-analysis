const form = document.getElementById("collect-form");
const statusElement = document.getElementById("task-status");
const successCountElement = document.getElementById("success-count");
const taskKeywordElement = document.getElementById("task-keyword");
const taskTargetCountElement = document.getElementById("task-target-count");
const taskExistingCountElement = document.getElementById("task-existing-count");
const taskAddedCountElement = document.getElementById("task-added-count");
const taskTotalCountElement = document.getElementById("task-total-count");
const taskCourseTargetElement = document.getElementById("task-course-target");
const taskCourseProgressElement = document.getElementById("task-course-progress");
const messageElement = document.getElementById("task-message");
const pollErrorElement = document.getElementById("poll-error");
const latestVideosNoteElement = document.getElementById("latest-videos-note");
const latestVideosElement = document.getElementById("latest-videos");
const cleanForm = document.getElementById("clean-form");
const cleanStatusElement = document.getElementById("clean-status");
const cleanBeforeElement = document.getElementById("clean-before");
const cleanAfterElement = document.getElementById("clean-after");
const cleanRemovedElement = document.getElementById("clean-removed");
const cleanResultDateElement = document.getElementById("clean-result-date");
const cleanMessageElement = document.getElementById("clean-message");
let pollingTimer = null;
let submissionGeneration = 0;
let currentTaskId = null;
let pollInFlight = false;
let cleanSubmissionGeneration = 0;

const collectDateElement = document.getElementById("collect-date");
collectDateElement.addEventListener("change", () => {
    location.href = `/collect?date=${encodeURIComponent(collectDateElement.value)}`;
});

function clearPollingTimer() {
    if (pollingTimer !== null) {
        clearInterval(pollingTimer);
    }
    pollingTimer = null;
}

function isCurrentTask(taskId, generation) {
    return taskId === currentTaskId && generation === submissionGeneration;
}

function stopPolling(taskId, generation) {
    if (isCurrentTask(taskId, generation)) {
        clearPollingTimer();
    }
}

function appendCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value ?? "";
    row.appendChild(cell);
}

function renderLatestVideos(videos) {
    latestVideosElement.replaceChildren();
    videos.forEach((video) => {
        const row = document.createElement("tr");
        const titleCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = video.video_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = video.title;
        titleCell.appendChild(link);
        row.appendChild(titleCell);
        appendCell(row, video.up_name);
        appendCell(row, video.view_count);
        appendCell(row, video.like_count);
        appendCell(row, video.coin_count);
        appendCell(row, video.favorite_count);
        appendCell(row, video.share_count);
        latestVideosElement.appendChild(row);
    });
}

async function readResponse(response) {
    let payload;
    try {
        payload = await response.json();
    } catch (error) {
        throw new Error(`请求失败：${response.status}，服务器返回了非 JSON 响应`);
    }
    if (!response.ok) {
        throw new Error(payload.message || `请求失败：${response.status}`);
    }
    return payload;
}

async function pollTask(taskId, generation) {
    const response = await fetch(`/api/collect/status/${taskId}`);
    const task = await readResponse(response);
    if (!isCurrentTask(taskId, generation)) {
        return;
    }

    pollErrorElement.textContent = "";
    statusElement.textContent = task.status;
    successCountElement.textContent = task.success_count;
    taskKeywordElement.textContent = task.keyword;
    taskTargetCountElement.textContent = task.target_count;
    taskExistingCountElement.textContent = task.existing_count ?? "--";
    taskAddedCountElement.textContent = task.added_count;
    taskTotalCountElement.textContent = task.total_count ?? "--";
    taskCourseTargetElement.textContent = task.course_target;
    taskCourseProgressElement.textContent = task.total_count === null
        ? "--"
        : `${(task.total_count / task.course_target * 100).toFixed(2)}%`;
    messageElement.textContent = task.message;

    if (task.status === "success" || task.status === "failed") {
        stopPolling(taskId, generation);
        latestVideosNoteElement.textContent = task.latest_videos_note;
        renderLatestVideos(task.latest_videos);
    }
}

async function refreshTask(taskId, generation) {
    if (!isCurrentTask(taskId, generation) || pollInFlight) {
        return;
    }

    pollInFlight = true;
    try {
        await pollTask(taskId, generation);
    } catch (error) {
        if (isCurrentTask(taskId, generation)) {
            pollErrorElement.textContent = `状态更新失败：${error.message}`;
        }
    } finally {
        if (isCurrentTask(taskId, generation)) {
            pollInFlight = false;
        }
    }
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submissionGeneration += 1;
    const generation = submissionGeneration;
    currentTaskId = null;
    clearPollingTimer();
    pollInFlight = false;
    messageElement.textContent = "";
    pollErrorElement.textContent = "";
    latestVideosNoteElement.textContent = "";
    renderLatestVideos([]);

    try {
        const response = await fetch("/api/collect", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                keyword: form.elements.keyword.value,
                date: form.elements.date.value,
                target_count: Number(form.elements.target_count.value),
            }),
        });
        const task = await readResponse(response);
        if (generation !== submissionGeneration) {
            return;
        }

        currentTaskId = task.task_id;
        statusElement.textContent = "waiting";
        await refreshTask(task.task_id, generation);
        if (!isCurrentTask(task.task_id, generation)) {
            return;
        }

        if (pollingTimer === null && statusElement.textContent !== "success" && statusElement.textContent !== "failed") {
            pollingTimer = setInterval(
                () => refreshTask(task.task_id, generation),
                2000,
            );
        }
    } catch (error) {
        if (generation === submissionGeneration) {
            statusElement.textContent = "failed";
            messageElement.textContent = error.message;
        }
    }
});

cleanForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    cleanSubmissionGeneration += 1;
    const generation = cleanSubmissionGeneration;
    const cleanDate = cleanForm.elements.date.value;
    cleanStatusElement.textContent = "正在清洗";
    cleanBeforeElement.textContent = "--";
    cleanAfterElement.textContent = "--";
    cleanRemovedElement.textContent = "--";
    cleanResultDateElement.textContent = cleanDate;
    cleanMessageElement.textContent = "";
    try {
        const response = await fetch("/api/clean", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({date: cleanDate}),
        });
        const result = await readResponse(response);
        if (generation !== cleanSubmissionGeneration) {
            return;
        }
        cleanBeforeElement.textContent = String(result.before_count);
        cleanAfterElement.textContent = String(result.after_count);
        cleanRemovedElement.textContent = String(result.removed_count);
        cleanStatusElement.textContent = "清洗完成";
        cleanMessageElement.textContent = result.message;
    } catch (error) {
        if (generation === cleanSubmissionGeneration) {
            cleanStatusElement.textContent = "清洗失败";
            cleanMessageElement.textContent = error.message;
        }
    }
});
