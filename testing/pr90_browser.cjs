const { chromium } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const context = await browser.newContext({ viewport: { width: 1360, height: 960 } });
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (request.url().endsWith("/api/chat")) requests.push(request.postDataJSON());
  });
  const composer = page.getByRole("textbox", { name: "Type your message" });
  const ready = () => page.waitForFunction(() => !document.querySelector("textarea")?.disabled);
  const response = () => page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  async function send(text) {
    await ready();
    await composer.fill(text);
    const pending = response();
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    const result = await (await pending).json();
    await ready();
    return result;
  }
  async function chooseStation(name) {
    await page.getByRole("button", { name: "Browse stations", exact: true }).click();
    await page.getByRole("searchbox", { name: "Search stations", exact: true }).fill(name);
    await page.getByRole("button", { name: new RegExp(name + ".*Choose") }).click();
  }
  try {
    await page.goto("http://127.0.0.1:8890");
    await ready();
    await chooseStation("Central source");
    const first = await send("Temperature here yesterday?");
    assert.equal(first.outcome, "success");
    await page.getByText("Sources and coverage", { exact: true }).last().click();
    const sourceText = await page.locator(".source-details").last().innerText();
    assert.match(sourceText, /average air temperature/);
    assert.ok(!sourceText.includes("AVG_AIR_TEMP"));
    assert.ok(!sourceText.includes("station 1"));
    assert.equal(requests.at(-1).mode, "weather");
    assert.equal(first.context.point, null);
    assert.equal(requests.at(-1).point, undefined);
    assert.ok(!JSON.stringify(first).includes("120.501"));
    const originalStation = requests.at(-1).station_id;
    assert.equal(originalStation, "1");
    await page.reload();
    await ready();
    assert.match(await page.locator(".message-row--assistant").last().innerText(), /70.25 F/);
    assert.equal(await page.locator(".source-details").count(), 1);
    const followup = await send("Humidity here?");
    assert.equal(requests.at(-1).point, undefined);
    assert.equal(requests.at(-1).station_id, undefined);
    assert.deepEqual(followup.context.station_ids, [originalStation]);
    const failure = await send("Retry weather");
    assert.match(failure.detail, /could not complete/);
    const failedRequest = requests.at(-1);
    await page.reload();
    await ready();
    await chooseStation("Eastern source");
    const retry = response();
    await page.getByRole("button", { name: "Retry message", exact: true }).click();
    assert.equal((await (await retry).json()).outcome, "success");
    await ready();
    assert.deepEqual(requests.at(-1), failedRequest);
    await page.getByRole("button", { name: "New conversation", exact: true }).first().click();
    await chooseStation("Eastern source");
    const current = await send("Wind here?");
    assert.equal(current.outcome, "success");
    assert.deepEqual(current.context.station_ids, ["2"]);
    await page.getByRole("combobox", { name: "Question type" }).selectOption("history");
    const history = await send("What did we discuss last time?");
    assert.equal(history.outcome, "history");
    assert.equal(requests.at(-1).mode, "history");
    assert.match(history.reply, /\[1\]/);
    assert.equal(requests.at(-1).point, undefined);
    await page.reload();
    await ready();
    assert.equal(await page.locator(".message-row--assistant .message-bubble p").last().innerText(), history.reply);
    await page.screenshot({ path: "/private/tmp/awn-pr90-desktop.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const sendButton = await page.getByRole("button", { name: "Send message", exact: true }).boundingBox();
    assert.ok(sendButton.y + sendButton.height <= 844, "Mobile composer must remain visible");
    await page.screenshot({ path: "/private/tmp/awn-pr90-mobile.png", fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, []);
    console.log("Browser checks passed: station selection, saved location reuse, restoration, retry input, history recall and mobile layout.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
