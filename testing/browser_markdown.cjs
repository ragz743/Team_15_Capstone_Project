// Start the frontend with npm run dev, then run with Playwright available:
// AWN_UI_URL=http://127.0.0.1:5173 node testing/browser_markdown.cjs
// API responses are intercepted; no backend, model, or database is used.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

const conversationId = "11111111-1111-4111-8111-111111111111";
const requestId = "22222222-2222-4222-8222-222222222222";
const timestamp = "2026-09-30T18:30:00Z";
const userText = "**Show weather**\n  Keep my spacing";
const responseText = [
  "## Latest weather in Pullman",
  "Whitman County · Observed September 30, 2026, at 11:30 AM",
  "- **Temperature:** 60.4°F\n- **Precipitation:** 0.00 inches\n- **Wind speed:** 9.5 mph",
  "| Date | Temperature | Precipitation | Wind speed | Humidity |\n| --- | ---: | ---: | ---: | ---: |\n| September 30 | 60.4°F | 0.00 inches | 9.5 mph | 65% |",
  "> These are the latest available readings.",
  "1. Check observations.\n2. Compare with the forecast.",
  "An `observation` is a recorded value. ~~Outdated~~ Updated.",
  "```text\nTemperature     60.4°F\n" + "long-code-line ".repeat(30) + "\n```",
  "[Station details](https://weather.wsu.edu/)",
  "[Unsafe link](javascript:alert%281%29) [Unsafe data](data:text/html,test)",
  '<script>window.markdownExecuted = true</script>\n<img src="https://example.invalid/raw.png" onerror="window.markdownExecuted = true">',
  "![Remote image](https://example.invalid/markdown.png)",
  "Source station: Pullman (station ID 100093), Whitman County.",
].join("\n\n");
const summary = { id: conversationId, title: "Weather formatting", created_at: timestamp, updated_at: timestamp };
const contextData = { station_ids: ["100093"], county: "Whitman", start: null, end: null, subject: "weather" };
const metadata = { outcome: "success", coverage: "complete", sources: [{
  station_id: "100093", station: "Pullman", county: "Whitman", kind: "observation",
  times: [timestamp], measurements: ["Temperature (°F)"],
}] };

(async () => {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  try {
    const context = await browser.newContext({ viewport: { width: 1360, height: 960 } });
    const page = await context.newPage();
    const errors = [], unexpectedRequests = [];
    page.on("pageerror", error => errors.push(error.message));
    await context.addInitScript(id => sessionStorage.setItem("awn.selectedConversation", id), conversationId);
    let messages = [
      { id: "saved-user", role: "user", content: userText, created_at: timestamp, status: "completed", request_id: requestId },
      { id: "saved-assistant", role: "assistant", content: responseText, created_at: timestamp, status: "completed", request_id: requestId, metadata },
    ];
    let releaseReply;
    const replyGate = new Promise(resolve => { releaseReply = resolve; });
    await page.route("https://example.invalid/**", route => {
      unexpectedRequests.push(route.request().url());
      return route.abort();
    });
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      let body;
      if (url.pathname === "/api/stations") {
        body = { stations: [{ id: "100093", name: "Pullman", county: "Whitman", distance_km: null }], counties: ["Whitman"], located_count: 1 };
      } else if (url.pathname === "/api/conversations") {
        body = { conversations: [summary] };
      } else if (url.pathname === `/api/conversations/${conversationId}`) {
        body = { ...summary, messages, context: contextData, next_before: null };
      } else if (url.pathname === "/api/chat") {
        const input = route.request().postDataJSON();
        await replyGate;
        const reply = "**Fresh response:** 60.4°F\n\n- Wind speed: **9.5 mph**";
        messages = [...messages,
          { id: "fresh-user", role: "user", content: input.message, created_at: timestamp, status: "completed", request_id: input.request_id },
          { id: "fresh-assistant", role: "assistant", content: reply, created_at: timestamp, status: "completed", request_id: input.request_id, metadata },
        ];
        body = { reply, model: "fixture", context: contextData, ...metadata, conversation_id: conversationId, request_id: input.request_id };
      } else {
        unexpectedRequests.push(url.pathname);
        return route.abort();
      }
      return route.fulfill({ json: body });
    });

    await page.goto(process.env.AWN_UI_URL || "http://127.0.0.1:5173");
    const markdown = page.locator(".assistant-markdown").first();
    await markdown.getByRole("heading", { name: "Latest weather in Pullman" }).waitFor();
    assert.equal(await markdown.locator("ul > li").count(), 3);
    assert.equal(await markdown.locator("ol > li").count(), 2);
    assert.equal(await markdown.locator("strong").first().innerText(), "Temperature:");
    assert.equal(await markdown.locator("table tbody tr").count(), 1);
    assert.equal(await markdown.locator("th").nth(1).evaluate(el => getComputedStyle(el).textAlign), "right");
    assert.equal(await markdown.locator("blockquote").count(), 1);
    assert.equal(await markdown.locator("pre code").count(), 1);
    assert.equal(await markdown.locator("del").innerText(), "Outdated");
    assert.equal(await markdown.getByRole("link", { name: "Station details" }).getAttribute("href"), "https://weather.wsu.edu/");
    for (const name of ["Unsafe link", "Unsafe data"]) {
      assert.equal(await markdown.getByText(name, { exact: true }).getAttribute("href"), "");
    }
    assert.equal(await markdown.locator("script, img, iframe").count(), 0);
    assert.equal(await page.evaluate(() => window.markdownExecuted), undefined);
    assert.doesNotMatch(await markdown.innerText(), /100093/);
    const user = page.locator(".message-row--user .message-bubble").first();
    assert.equal(await user.innerText(), userText);
    assert.equal(await user.locator("strong").count(), 0);
    assert.equal(await user.locator("p").evaluate(el => getComputedStyle(el).whiteSpace), "pre-wrap");
    const paragraphStyle = await markdown.locator("p").first().evaluate(el => ({
      whitespace: getComputedStyle(el).whiteSpace, margin: parseFloat(getComputedStyle(el).marginBottom),
    }));
    assert.equal(paragraphStyle.whitespace, "normal");
    assert.ok(paragraphStyle.margin > 0);
    await page.getByText("Sources and coverage", { exact: true }).first().click();
    assert.match(await page.locator(".source-details").first().innerText(), /Pullman, Whitman County/);

    for (const width of [1360, 390, 320]) {
      await page.setViewportSize({ width, height: 960 });
      const layout = await page.evaluate(() => {
        const transcript = document.querySelector(".transcript");
        const table = document.querySelector(".markdown-table-scroll");
        return {
          pageFits: document.documentElement.scrollWidth <= innerWidth,
          chatFits: transcript.scrollWidth <= transcript.clientWidth + 1,
          tableScrolls: table.scrollWidth > table.clientWidth,
        };
      });
      assert.ok(layout.pageFits && layout.chatFits, `No horizontal page overflow at ${width}px`);
      if (width < 400) assert.ok(layout.tableScrolls, "Wide tables scroll on mobile");
      await markdown.getByRole("region", { name: "Response table" }).focus();
      assert.equal(await page.evaluate(() => document.activeElement.className), "markdown-table-scroll");
    }

    await page.setViewportSize({ width: 1360, height: 960 });
    await page.getByRole("textbox", { name: "Type your message" }).fill("Weather now?");
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "Preparing your response" }).waitFor();
    releaseReply();
    await page.locator(".assistant-markdown").last().getByText("Fresh response:", { exact: true }).waitFor();
    assert.equal(await page.locator(".assistant-markdown").last().locator("strong").count(), 2);
    await page.reload();
    await page.locator(".assistant-markdown").last().getByText("Fresh response:", { exact: true }).waitFor();
    assert.equal(await page.locator(".assistant-markdown").count(), 2);
    assert.equal(await page.locator(".message-pending").count(), 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpectedRequests, []);
    if (process.env.AWN_SCREENSHOT) {
      await page.locator(".transcript").evaluate(el => { el.scrollTop = 0; });
      await page.screenshot({ path: process.env.AWN_SCREENSHOT });
    }
    console.log("PASS: saved/fresh Markdown, reload, user whitespace, source disclosure, safe HTML/URLs, and desktop/mobile layout");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
