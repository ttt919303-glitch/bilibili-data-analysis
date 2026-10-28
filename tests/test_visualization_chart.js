const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const template = fs.readFileSync(
    path.join(__dirname, "..", "templates", "visualization.html"),
    "utf8"
);
const inlineScripts = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const chartScript = inlineScripts.at(-1)[1].replace(
    /const analysis = .*?;/,
    `const analysis = ${JSON.stringify({
        up_video_count: [{ name: "大数据技术入门精讲完整标题", value: 10 }],
        top_views: [{ name: "大数据技术入门精讲完整标题", value: 20 }],
        top_likes: [{ name: "大数据技术入门精讲完整标题", value: 30 }],
        top_interactions: [{ name: "大数据技术入门精讲完整标题", value: 40 }],
    })};`
);
const chartOptions = [];
const context = {
    document: { getElementById: (id) => ({ id }) },
    echarts: {
        init: () => ({
            setOption: (option) => chartOptions.push(option),
        }),
    },
};

vm.runInNewContext(chartScript, context);

assert.equal(chartOptions.length, 4);
for (const option of chartOptions) {
    assert.equal(option.xAxis.data[0], "大数据技术入门精讲完整标题");
    assert.equal(
        option.xAxis.axisLabel.formatter("大数据技术入门精讲完整标题"),
        "大数据技术入门精讲完…"
    );
    assert.equal(option.xAxis.axisLabel.rotate, 45);
    assert.equal(option.xAxis.axisLabel.interval, 0);
    assert.equal(option.grid.bottom, 110);
    assert.equal(option.grid.containLabel, true);
    assert.equal(option.tooltip.appendToBody, true);
    assert.equal(option.tooltip.confine, true);
    assert.match(option.tooltip.extraCssText, /max-width: 320px/);
    assert.match(option.tooltip.extraCssText, /white-space: normal/);
    assert.deepEqual(
        [...option.tooltip.position(
            [80, 100],
            [],
            null,
            null,
            { viewSize: [447, 360], contentSize: [320, 80] }
        )],
        [92, 60]
    );

    const tooltip = option.tooltip.formatter([
        {
            data: { name: "大数据技术入门精讲完整标题", value: 123 },
            value: 123,
        },
    ]);
    assert.match(tooltip, /大数据技术入门精讲完整标题/);
    assert.match(tooltip, /123/);
}
