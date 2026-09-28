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
  async function chooseNearbyPoint() {
    const map = page.getByRole("region", { name: "Choose weather location on map" });
    const bounds = await map.boundingBox();
    assert.ok(bounds);
    await map.click({ position: { x: bounds.width / 2 + 16, y: bounds.height / 2 } });
  }
  try {
    await page.goto("http://127.0.0.1:8890");
    await ready();
    assert.equal(await page.getByRole("button", { name: "Browse stations", exact: true }).count(), 0);
    await page.getByRole("button", { name: "Use map center", exact: true }).click();
    const first = await send("Temperature here yesterday?");
    assert.equal(first.outcome, "success");
    assert.ok(first.context.point);
    assert.ok(!JSON.stringify(first).includes("120.501"));
    const originalPoint = requests.at(-1).point;
    await page.reload();
    await ready();
    assert.match(await page.locator(".message-row--assistant").last().innerText(), /72 F/);
    const followup = await send("Humidity here?");
    assert.equal(requests.at(-1).point, undefined);
    assert.deepEqual(followup.context.point, originalPoint);
    const failure = await send("Retry weather");
    assert.match(failure.detail, /could not complete/);
    const failedRequest = requests.at(-1);
    await page.reload();
    await ready();
    await page.locator(".map-panel summary").click();
    await chooseNearbyPoint();
    const retry = response();
    await page.getByRole("button", { name: "Retry message", exact: true }).click();
    assert.equal((await (await retry).json()).outcome, "success");
    await ready();
    assert.deepEqual(requests.at(-1), failedRequest);
    await page.getByRole("button", { name: "New conversation", exact: true }).first().click();
    await chooseNearbyPoint();
    const current = await send("Wind here?");
    assert.equal(current.outcome, "success");
    assert.notDeepEqual(current.context.point, originalPoint);
    const reused = await send("Using our last conversation, what about humidity?");
    assert.equal(reused.outcome, "success");
    assert.deepEqual(reused.context.point, originalPoint);
    assert.equal(requests.at(-1).point, undefined);
    const selected = `Selected point: ${originalPoint.latitude.toFixed(4)}, ${originalPoint.longitude.toFixed(4)}`;
    await page.locator(".map-panel summary").click();
    assert.equal(await page.locator('.location-controls [role="status"]').innerText(), selected);
    await page.reload();
    await ready();
    await page.locator(".map-panel summary").click();
    assert.equal(await page.locator('.location-controls [role="status"]').innerText(), selected);
    const history = await send("What did we discuss last time?");
    assert.equal(history.outcome, "history");
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
    console.log("Browser checks passed: map selection, saved location reuse, restoration, retry input, history recall and mobile layout.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
