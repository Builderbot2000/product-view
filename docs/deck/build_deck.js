// Build docs/deck/product-view-pitch.pptx: the proposal deck for senior managers (pitch-deck-brief.md,
// revisions of 2026-10-23 and 2026-11-02). Slide sources live in out/deck/sources.md, not in the deck.
// Run from the repo root: NODE_PATH=<node_modules dir> PPTX_SKILL=<pptx skill dir> node docs/deck/build_deck.js
// Needs pptxgenjs, react, react-dom, react-icons, sharp and js-yaml. Inputs are in docs/deck/assets/:
// two charts rasterised from the demo report (out/report-proofread/) and the logo.
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = process.env.DECK_OUT || "docs/deck/product-view-pitch.pptx";
const ASSETS = "docs/deck/assets";

// RBC brand guide 6.1, "Mass" palette: Bright Blue Tint 1 (digital primary) 006AC3, Bright Blue
// 0051A5, Cool White E7EEF1, Warm Yellow FFC72C; Dark Blue 003168 is for High Net Worth only.
// Body text is black (guide 5.5). The greys (accent3-5) are neutrals the guide does not specify.
const THEME = {
  name: "Product View (RBC brand)",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: "000000", lt1: "FFFFFF", dk2: "0051A5", lt2: "E7EEF1",
    accent1: "006AC3", accent2: "FFC72C", accent3: "596069", accent4: "DDE3E7",
    accent5: "B3B8BE", accent6: "003168", hlink: "006AC3", folHlink: "0051A5",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Product View: internal proposal";
pres.author = "Kevin Tang";
pres.company = "RBC";
const C = pres.SchemeColor;

// ---------- layouts ----------
const W = 13.333;
const M = 0.6; // side margin
const CW = W - 2 * M; // content width

const slideNum = () => ({ x: M, y: 6.98, w: 0.5, h: 0.32, fontSize: 11, color: HEX.accent3, align: "left" });
// RBC logo, bottom-right as in every guide sample. 0.5" tall = 48px, the digital minimum (guide 3.4).
// Source: en.wikipedia.org File:RBC_Royal_Bank.svg (not an RBC-supplied file), rendered to PNG.
const LOGO_PNG = path.join(ASSETS, "rbc-logo-small.png"); // 400 px tall
const LOGO_RATIO = 277.35 / 360.56; // width / height of the shield
const logoAt = (right, y, h) => ({ image: { x: right - h * LOGO_RATIO, y, w: h * LOGO_RATIO, h, path: LOGO_PNG, altText: "RBC logo" } });
const logoObjs = () => [logoAt(W - M, 6.85, 0.5)];
const titlePh = () => ({
  placeholder: {
    options: { name: "title", type: "title", x: M, y: 0.38, w: CW, h: 0.95, fontSize: 32, bold: false, color: C.accent1, valign: "middle", align: "left", margin: 0 },
    text: "",
  },
});

pres.defineSlideMaster({
  title: "PV Title",
  background: { color: HEX.lt2 },
  objects: [
    logoAt(W - M, 6.3, 0.85),
    { placeholder: { options: { name: "title", type: "title", x: M, y: 1.4, w: 10.2, h: 1.6, fontSize: 54, bold: false, color: C.accent1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "subtitle", type: "body", x: M, y: 3.2, w: 10.2, h: 1.1, fontSize: 22, color: C.text2, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "PV Closing",
  background: { color: HEX.lt2 },
  objects: [
    logoAt(W - M, 6.3, 0.85),
    { placeholder: { options: { name: "title", type: "title", x: M, y: 0.9, w: CW, h: 1.2, fontSize: 40, bold: false, color: C.accent1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "PV Title Only",
  background: { color: HEX.lt1 },
  objects: [titlePh(), ...logoObjs()],
  slideNumber: slideNum(),
});
pres.defineSlideMaster({
  title: "PV Text and Visual",
  background: { color: HEX.lt1 },
  objects: [
    titlePh(),
    { placeholder: { options: { name: "body", type: "body", x: M, y: 1.65, w: 5.6, h: 4.9, fontSize: 18, color: C.text1, valign: "top", margin: 0, paraSpaceAfter: 14 }, text: "" } },
    ...logoObjs(),
  ],
  slideNumber: slideNum(),
});

// ---------- helpers ----------
async function icon(Comp, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
async function iconCircle(slide, Comp, x, y, d, name, fill = C.accent1, fg = HEX.lt1) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: name + " circle" });
  const p = d * 0.25;
  slide.addImage({ data: await icon(Comp, fg), x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p, objectName: name + " icon" });
}
function card(slide, x, y, w, h, name, fill = C.background2) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { type: "none" }, objectName: name });
}
function outline(slide, x, y, w, h, name) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { type: "none" }, line: { color: C.accent4, width: 1 }, objectName: name + " border" });
}
function text(slide, t, opts) {
  slide.addText(t, { isTextBox: true, margin: 0, valign: "top", color: C.text1, fontSize: 16, ...opts });
}
function caption(slide, t, x, y, w, h = 0.3) {
  text(slide, t, { x, y, w, h, fontSize: 11, color: C.accent3, objectName: "Caption" });
}
function band(slide, t, y, h = 0.6, name = "Band") {
  card(slide, M, y, CW, h, name, C.accent1);
  text(slide, t, { x: M + 0.35, y, w: CW - 0.7, h, fontSize: 16, bold: true, color: C.background1, valign: "middle", objectName: name + " text" });
}
function marker(slide, x, y, name) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.24, h: 0.24, fill: { color: C.accent2 }, line: { color: C.accent1, width: 1 }, objectName: name });
}
function arrow(slide, x, y, name) {
  slide.addShape(pres.shapes.RIGHT_ARROW, { x, y, w: 0.34, h: 0.34, fill: { color: C.accent1 }, line: { type: "none" }, objectName: name });
}
function imgFit(file, maxW, maxH) {
  const b = fs.readFileSync(file);
  const iw = b.readUInt32BE(16), ih = b.readUInt32BE(20);
  const s = Math.min(maxW / iw, maxH / ih);
  return { w: iw * s, h: ih * s };
}
// Cover art: overlapping circles bleeding off the top-right corner, in the primary palette.
function coverArt(slide) {
  slide.addShape(pres.shapes.OVAL, { x: 8.9, y: -2.6, w: 6.4, h: 6.4, fill: { color: C.accent1 }, line: { type: "none" }, objectName: "Cover circle large" });
  slide.addShape(pres.shapes.OVAL, { x: 11.2, y: -1.3, w: 3.6, h: 3.6, fill: { color: C.text2 }, line: { type: "none" }, objectName: "Cover circle dark" });
  slide.addShape(pres.shapes.OVAL, { x: 9.55, y: 2.55, w: 1.25, h: 1.25, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "Cover circle yellow" });
}
const bullets = (items) => items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } }));

// ---------- slides ----------
async function build() {
  const yaml = require(require.resolve("js-yaml"));
  const matrix = yaml.load(fs.readFileSync("matrix.sample.yaml", "utf8"));

  // 1. Title
  pres.addSection({ title: "Opening" });
  let s = pres.addSlide({ masterName: "PV Title", sectionTitle: "Opening" });
  s.addText("Product View", { placeholder: "title" });
  s.addText([
    { text: "Every customer heard. Every team knows what to fix next.", options: { breakLine: true } },
    { text: "RBC Mobile app reviews, sorted by feature and sent to the team that owns it", options: { fontSize: 16, color: C.text1, breakLine: true } },
    { text: "Internal proposal · November 2026 · Kevin Tang", options: { fontSize: 14, color: C.accent3 } },
  ], { placeholder: "subtitle" });
  coverArt(s);
  s.addNotes(
`TALK TRACK (about 30 s)
I'm here to propose a project called Product View. It takes the reviews customers leave for the RBC Mobile app on Google Play, sorts them by the app feature they're about, and sends each team a report every period on just the features it owns. I'll cover the need, what the product team asked for, how it works, and what it takes to run it at RBC.`);

  // 2. The need
  pres.addSection({ title: "The need" });
  s = pres.addSlide({ masterName: "PV Text and Visual", sectionTitle: "The need" });
  s.addText("Today, reviews reach the team one at a time", { placeholder: "title" });
  s.addText([
    { text: "Customers rate the RBC Mobile app on Google Play and often explain why in a few lines.", options: { breakLine: true } },
    { text: "Each new review is posted on its own into a Slack channel.", options: { breakLine: true } },
    { text: "Nobody can see which features are hurting, which problems are growing, or how many customers each one affects.", options: { breakLine: true } },
    { text: "In August 2026 alone, 84 complaints arrived as 84 separate messages.", options: { bold: true } },
  ], { placeholder: "body" });
  const stats = [
    ["21,506", "written reviews by Canadian customers since 2011"],
    ["13,930", "of them rated 1 to 3 stars out of 5"],
    ["604", "complaints so far in 2026 (January to September)"],
  ];
  stats.forEach(([n, l], i) => {
    const y = 1.65 + i * 1.7;
    card(s, 7.0, y, 5.73, 1.4, "Stat card " + (i + 1));
    text(s, n, { x: 7.3, y: y + 0.2, w: 2.5, h: 1.0, fontSize: 40, bold: true, color: C.accent1, valign: "middle", objectName: "Stat number " + (i + 1) });
    text(s, l, { x: 9.8, y: y + 0.2, w: 2.75, h: 1.0, fontSize: 16, valign: "middle", objectName: "Stat label " + (i + 1) });
  });
  s.addNotes(
`TALK TRACK (about 1 min)
When customers rate our app on Google Play, many of them write a few lines saying why. Today those reviews reach the Mobile team one at a time: each new review is posted on its own into a Slack channel. That's fine for reading one review, but it can't tell a team how its part of the app is doing: which features are hurting, which problems are growing, how many customers each one affects. And there are a lot of them: over twenty-one thousand written reviews from Canadian customers since 2011 and nearly fourteen thousand of them rated 1 to 3 stars. They keep coming, too: 604 complaints so far this year, and in August alone, 84 complaints arrived as 84 separate messages.`);

  // 3. What the Mobile product team asked for
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The need" });
  s.addText("What the Mobile product team asked for", { placeholder: "title" });
  card(s, M, 1.6, 4.6, 3.7, "Ask card", C.accent1);
  await iconCircle(s, fa.FaEnvelopeOpenText, M + 0.35, 1.9, 0.85, "Ask", C.background1, HEX.accent1);
  text(s, "An email each period for each team, on just the features it owns", { x: M + 0.35, y: 2.95, w: 3.9, h: 1.4, fontSize: 22, bold: true, color: C.background1 });
  text(s, "What customers said, how much, and whether it's getting better or worse", { x: M + 0.35, y: 4.35, w: 3.9, h: 0.8, fontSize: 15, color: C.background1 });
  const gets = [
    [fa.FaSearch, "Analysts", "A head start: the numbers and quotes for their own reports"],
    [fa.FaClipboardList, "Feature owners", "Just their features, in their inbox, every period"],
    [fa.FaCodeBranch, "Engineering", "Which app release started a problem"],
    [fa.FaHeadset, "Customer support", "What customers raise, in their own words"],
  ];
  const gx = M + 4.6 + 0.4, gw = (W - M - gx - 0.3) / 2, gh = 1.7;
  for (let i = 0; i < gets.length; i++) {
    const [Ic, h, b] = gets[i];
    const x = gx + (i % 2) * (gw + 0.3), y = 1.6 + Math.floor(i / 2) * (gh + 0.3);
    card(s, x, y, gw, gh, "Benefit card " + (i + 1));
    await iconCircle(s, Ic, x + 0.3, y + 0.3, 0.6, "Benefit " + (i + 1));
    text(s, h, { x: x + 1.1, y: y + 0.3, w: gw - 1.35, h: 0.6, fontSize: 17, bold: true, color: C.text2, valign: "middle" });
    text(s, b, { x: x + 0.3, y: y + 1.0, w: gw - 0.6, h: 0.65, fontSize: 14 });
  }
  band(s, "Product View answers that ask, inspired by RBC's push to put AI to work.", 5.65, 0.75, "Inspiration band");
  s.addNotes(
`TALK TRACK (about 1 min)
The Mobile product team asked for something simple: an email each period for each team, covering only the features that team owns. What customers said, how much, and whether it's getting better or worse.
That helps everyone around the app: analysts get a head start on their reports, feature owners get just their features, engineering sees which release started a problem, and support hears customers in their own words.
RBC's push to put AI to work inspired this project. Product View is my proposal to deliver what the product team asked for.`);

  // 4. Requirements
  pres.addSection({ title: "The proposal" });
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The proposal" });
  s.addText("What it must do", { placeholder: "title" });
  const showTeams = ["sign-in-security", "payments"];
  const chipH = 0.31, step = 0.37, teamGap = 0.25;
  let yy = 1.9;
  text(s, "Team", { x: M, y: 1.55, w: 2.3, h: 0.3, fontSize: 12, bold: true, color: C.accent3 });
  text(s, "Owner", { x: 3.15, y: 1.55, w: 2.1, h: 0.3, fontSize: 12, bold: true, color: C.accent3 });
  text(s, "Features they own", { x: 5.5, y: 1.55, w: 3.2, h: 0.3, fontSize: 12, bold: true, color: C.accent3 });
  for (const tid of showTeams) {
    const team = matrix.teams[tid];
    const n = team.members.reduce((a, m) => a + m.topics.length, 0);
    const th = n * step - (step - chipH);
    card(s, M, yy, 2.3, th, "Team " + tid, C.accent1);
    text(s, team.name, { x: M + 0.15, y: yy, w: 2.0, h: th, fontSize: 15, bold: true, color: C.background1, valign: "middle" });
    let my = yy;
    for (const mem of team.members) {
      const mh = mem.topics.length * step - (step - chipH);
      card(s, 3.15, my, 2.1, mh, "Member " + mem.name);
      text(s, mem.name, { x: 3.3, y: my, w: 1.8, h: mh, fontSize: 14, bold: true, color: C.text2, valign: "middle" });
      mem.topics.forEach((tp, k) => {
        const ty = my + k * step;
        s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.5, y: ty, w: 3.2, h: chipH, rectRadius: 0.06, fill: { color: C.background1 }, line: { color: C.accent4, width: 1 }, objectName: "Topic " + tp });
        text(s, matrix.topics[tp].name, { x: 5.62, y: ty, w: 3.0, h: chipH, fontSize: 12, valign: "middle" });
      });
      my += mem.topics.length * step;
    }
    yy += n * step + teamGap;
  }
  caption(s, "An example Ownership Matrix. The teams decide what goes in it.", M, yy - 0.05, 8.1);
  const musts = [
    ["Your features only", "Each owner sees just the features they own"],
    ["Public reviews only", "Only what customers posted on Google Play"],
    ["Data stays inside RBC", "Runs in RBC's own cloud, Azure or AWS"],
    ["Numbers you can check", "Counts of real reviews, quotes that link back"],
    ["Runs by itself", "Every period, with nobody starting it"],
  ];
  musts.forEach(([h, b], i) => {
    const y = 1.55 + i * 0.98, x = 9.15;
    marker(s, x, y + 0.08, "Marker " + (i + 1));
    text(s, h, { x: x + 0.4, y, w: 3.18, h: 0.38, fontSize: 16, bold: true, color: C.text2 });
    text(s, b, { x: x + 0.4, y: y + 0.38, w: 3.18, h: 0.5, fontSize: 13 });
  });
  s.addNotes(
`TALK TRACK (about 1 min)
Here's what it has to do. It starts from one list, the Ownership Matrix: the teams, the people in each team, and the specific app features each person owns. The teams set it; the tool never invents its own features, so "change password or PIN" means the same thing in every report.
And it has to fit the bank: each owner sees only their own features; it reads only what customers have posted publicly on Google Play; the data stays inside RBC's own cloud, Azure or AWS; every number is a count of real reviews and every quote links back to the review it came from; and it runs by itself every period.`);

  // 5. At a glance: the whole project on one slide, in native shapes so it can be restyled.
  // The cloud pieces (formerly their own slide) sit in a strip inside the cloud box, named
  // generically so the cloud team picks the products (Kevin, 2026-11-04).
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The proposal" });
  s.addText("Product View at a glance", { placeholder: "title" });
  const flowLine = (x1, y1, x2, y2, name) => s.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), flipV: y2 < y1,
    line: { color: C.accent1, width: 2.25, endArrowType: "triangle" }, objectName: name,
  });
  const srcX = M, srcW = 1.6, rowY = 2.1, rowH = 1.85;
  const bx = 2.55, bw = 7.95, by = 1.4, bh = 4.55;
  // Source, left
  card(s, srcX, rowY, srcW, rowH, "Source card");
  await iconCircle(s, fa.FaGooglePlay, srcX + 0.15, rowY + 0.15, 0.5, "Source");
  text(s, "Google Play", { x: srcX + 0.15, y: rowY + 0.75, w: srcW - 0.25, h: 0.33, fontSize: 15, bold: true, color: C.text2 });
  text(s, "Reviews customers post publicly", { x: srcX + 0.15, y: rowY + 1.08, w: srcW - 0.25, h: 0.7, fontSize: 12 });
  // RBC's cloud boundary, middle
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: bx, y: by, w: bw, h: bh, rectRadius: 0.12, fill: { color: C.background1 }, line: { color: C.accent1, width: 1.5, dashType: "dash" }, objectName: "Cloud boundary" });
  await iconCircle(s, fa.FaCloud, bx + 0.25, by + 0.1, 0.45, "Cloud boundary");
  text(s, "Inside RBC's cloud (Azure or AWS)", { x: bx + 0.8, y: by + 0.1, w: 4.0, h: 0.45, fontSize: 15, bold: true, color: C.accent1, valign: "middle" });
  await iconCircle(s, fa.FaCalendarCheck, bx + bw - 2.85, by + 0.12, 0.4, "Schedule", C.accent2, HEX.dk2);
  text(s, "Runs itself every period", { x: bx + bw - 2.35, y: by + 0.1, w: 2.15, h: 0.45, fontSize: 13, bold: true, color: C.text2, valign: "middle" });
  const pipe = [
    [fa.FaCloudDownloadAlt, "Collect", "Picks up the latest Google Play reviews"],
    [fa.FaTags, "Sort", "AI ties each complaint to a feature"],
    [fa.FaChartBar, "Count", "Tallies each feature and spots what's rising"],
    [fa.FaFileAlt, "Write", "Builds the team pages and owner reports"],
  ];
  const px0 = bx + 0.25, pgap = 0.3, pw = (bw - 0.5 - 3 * pgap) / 4;
  const colX = (i) => px0 + i * (pw + pgap);
  for (let i = 0; i < pipe.length; i++) {
    const [Ic, h, b] = pipe[i];
    const x = colX(i);
    card(s, x, rowY, pw, rowH, "Pipeline card " + (i + 1));
    await iconCircle(s, Ic, x + 0.15, rowY + 0.15, 0.5, "Pipeline " + (i + 1));
    text(s, String(i + 1), { x: x + pw - 0.45, y: rowY + 0.15, w: 0.3, h: 0.5, fontSize: 14, bold: true, color: C.accent3, align: "right", valign: "middle" });
    text(s, h, { x: x + 0.15, y: rowY + 0.75, w: pw - 0.25, h: 0.33, fontSize: 15, bold: true, color: C.text2 });
    text(s, b, { x: x + 0.15, y: rowY + 1.08, w: pw - 0.25, h: 0.72, fontSize: 12 });
    if (i < pipe.length - 1) flowLine(x + pw + 0.03, rowY + rowH / 2, x + pw + pgap - 0.03, rowY + rowH / 2, "Pipeline arrow " + (i + 1));
  }
  flowLine(srcX + srcW + 0.03, rowY + rowH / 2, px0 - 0.03, rowY + rowH / 2, "Source arrow");
  // What the run keeps, under the steps
  const kY = 4.25, kH = 0.82;
  const keep = [
    [fa.FaSitemap, "Ownership Matrix", "Which team and person owns each feature", 0, 1],
    [fa.FaDatabase, "Review history", "Every past review, so trends can look back 12 periods", 2, 3],
  ];
  for (const [Ic, h, b, from, to] of keep) {
    const x = colX(from), w = colX(to) + pw - x;
    card(s, x, kY, w, kH, h + " card", C.background2);
    outline(s, x, kY, w, kH, h);
    await iconCircle(s, Ic, x + 0.15, kY + 0.16, 0.5, h);
    text(s, h, { x: x + 0.8, y: kY + 0.08, w: w - 0.95, h: 0.33, fontSize: 14, bold: true, color: C.text2 });
    text(s, b, { x: x + 0.8, y: kY + 0.4, w: w - 0.95, h: 0.4, fontSize: 11 });
  }
  flowLine(colX(1) + pw / 2, kY - 0.03, colX(1) + pw / 2, rowY + rowH + 0.03, "Matrix arrow");
  flowLine(colX(2) + pw / 2, kY - 0.03, colX(2) + pw / 2, rowY + rowH + 0.03, "History arrow");
  // The standard cloud pieces it runs on
  const pieces = [
    [fa.FaCalendarCheck, "Scheduler"], [fa.FaRobot, "AI service"], [fa.FaDatabase, "Storage"],
    [fa.FaKey, "Secret store"], [fa.FaPaperPlane, "Mail relay"], [fa.FaHeartbeat, "Monitoring"],
  ];
  const cY = 5.32, cH = 0.45, cgap = 0.1, cw = (bw - 0.5 - 5 * cgap) / 6;
  for (let i = 0; i < pieces.length; i++) {
    const [Ic, h] = pieces[i];
    const x = px0 + i * (cw + cgap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: cY, w: cw, h: cH, rectRadius: 0.06, fill: { color: C.accent1 }, line: { type: "none" }, objectName: "Cloud piece " + h });
    s.addImage({ data: await icon(Ic, HEX.lt1), x: x + 0.09, y: cY + 0.125, w: 0.2, h: 0.2, objectName: "Cloud piece icon " + h });
    text(s, h, { x: x + 0.34, y: cY, w: cw - 0.36, h: cH, fontSize: 10, bold: true, color: C.background1, valign: "middle" });
  }
  // Outputs, right
  const ox = bx + bw + 0.35, ow = W - M - ox, oh = 1.2;
  const outs = [
    [fa.FaUsers, "Team page", "Each team's big picture, on our wiki", 1.85],
    [fa.FaEnvelope, "Personal email", "Just the features they own", 3.2],
  ];
  for (const [Ic, h, b, y] of outs) {
    card(s, ox, y, ow, oh, h + " card", C.accent1);
    await iconCircle(s, Ic, ox + 0.15, y + 0.15, 0.45, h, C.background1, HEX.accent1);
    text(s, h, { x: ox + 0.7, y: y + 0.15, w: ow - 0.8, h: 0.45, fontSize: 14, bold: true, color: C.background1, valign: "middle" });
    text(s, b, { x: ox + 0.15, y: y + 0.65, w: ow - 0.25, h: 0.5, fontSize: 11, color: C.background1 });
    flowLine(colX(3) + pw + 0.03, y + oh / 2, ox - 0.03, y + oh / 2, h + " arrow");
  }
  text(s, "Read by analysts, feature owners, engineering and customer support", { x: ox, y: 4.6, w: ow, h: 0.9, fontSize: 12, color: C.accent3 });
  band(s, "Every period, customer reviews go in and every feature owner gets a report.", 6.15, 0.55, "Glance band");
  s.addNotes(
`TALK TRACK (about 1.5 min)
Here's the whole project on one page. Customers post reviews publicly on Google Play. Every period, Product View runs on its own inside RBC's cloud. First it picks up the latest reviews. Then the AI works out which feature each complaint is about, using the Ownership Matrix, our list of who owns which feature. Next it tallies each feature, compares it with a normal period and checks which app versions the complaints came from, drawing on the review history it keeps. Last, it writes the reports.
Each team gets a page on our wiki with its big picture, and each owner gets an email with just the features they own. Analysts, feature owners, engineering and support all read them.
Underneath, it runs on six standard pieces that both of our clouds already offer: a scheduler, an AI service, storage, a secret store for passwords, a mail relay and monitoring. The cloud team picks the product for each one.
IF ASKED: a review can match several features, or none; the ones that match none are still counted, so we can see if the matrix is missing something.
IF ASKED: the choice between Azure and AWS is the cloud team's; Product View ships as a standard container, so it moves between them without changes. The AI service can be any approved one inside RBC, including one we already run in-house; review text never goes to an outside service.`);

  // 6. How a report is put together
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The proposal" });
  s.addText("How each report is put together", { placeholder: "title" });
  text(s, "For every feature, every period", { x: M, y: 1.55, w: 6.6, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
  const recipe = [
    ["Count", "How many customers complained about it in the latest period"],
    ["Compare", "Against a normal period, so rising and new problems stand out"],
    ["Trace", "Which app versions the complaints came from"],
    ["Show", "Customers' own words, with star rating, date and app version"],
  ];
  recipe.forEach(([h, b], i) => {
    const y = 2.2 + i * 1.08;
    s.addShape(pres.shapes.OVAL, { x: M, y, w: 0.62, h: 0.62, fill: { color: C.accent1 }, line: { color: C.accent2, width: 2 }, objectName: "Recipe number " + (i + 1) });
    text(s, String(i + 1), { x: M, y, w: 0.62, h: 0.62, fontSize: 20, bold: true, color: C.background1, align: "center", valign: "middle" });
    text(s, h, { x: M + 0.95, y: y - 0.02, w: 5.6, h: 0.38, fontSize: 18, bold: true, color: C.text2 });
    text(s, b, { x: M + 0.95, y: y + 0.36, w: 5.6, h: 0.6, fontSize: 15 });
  });
  const tx = 7.65, tw = W - M - tx;
  card(s, tx, 1.55, tw, 5.0, "Trust card");
  await iconCircle(s, fa.FaShieldAlt, tx + 0.35, 1.85, 0.75, "Trust");
  text(s, "Built to be trusted", { x: tx + 1.3, y: 1.85, w: tw - 1.6, h: 0.75, fontSize: 20, bold: true, color: C.text2, valign: "middle" });
  s.addText(bullets([
    "The AI only decides which feature a review is about",
    "Every number is a plain count of real reviews",
    "Every quote links back to the review it came from",
    "The Ownership Matrix stays the same, so trends mean the same thing from one period to the next",
  ]), { isTextBox: true, x: tx + 0.4, y: 2.9, w: tw - 0.8, h: 3.4, fontSize: 16, color: C.text1, margin: 0, valign: "top", paraSpaceAfter: 12, objectName: "Trust list" });
  s.addNotes(
`TALK TRACK (about 1 min)
Once reviews are sorted, building a report is plain arithmetic. For every feature, every period: count how many customers complained about it in the latest period; compare that with a normal period, so anything rising or new stands out; trace which app versions the complaints came from, so a bad release shows up; and show customers' own words, with the star rating, date and version.
That's why the numbers can be trusted. The AI has one narrow job, deciding which feature a review is about. Every number is a count of real reviews, and every quote links back to the review it came from, so anyone can check it. And because the Ownership Matrix stays the same, a trend means the same thing from one period to the next.`);

  // 7. What teams receive
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The proposal" });
  s.addText("What teams receive", { placeholder: "title" });
  const lw = 6.1;
  text(s, "Team page: the big picture", { x: M, y: 1.5, w: lw, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  const ar = imgFit(path.join(ASSETS, "hub-areas.png"), lw, 3.4);
  s.addImage({ path: path.join(ASSETS, "hub-areas.png"), x: M, y: 2.05, w: ar.w, h: ar.h, altText: "Chart from the demo: complaints by product area in the latest period against normal, with the areas that rose flagged", objectName: "Team page chart" });
  caption(s, "Complaints by product area, latest period vs. normal. Red = up.", M, 2.05 + ar.h + 0.1, lw);
  const ex = M + lw + 0.4, exw = W - M - ex;
  text(s, "Personal email: your features", { x: ex, y: 1.5, w: exw, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  card(s, ex, 2.05, exw, 3.55, "Example card", C.background1);
  outline(s, ex, 2.05, exw, 3.55, "Example card");
  text(s, "Can't confirm a new phone as a trusted device", { x: ex + 0.3, y: 2.25, w: exw - 2.6, h: 0.75, fontSize: 16, bold: true, color: C.text2 });
  const sp = imgFit(path.join(ASSETS, "spark-2fa.png"), 1.9, 0.45);
  s.addImage({ path: path.join(ASSETS, "spark-2fa.png"), x: ex + exw - 0.3 - sp.w, y: 2.3, w: sp.w, h: sp.h, altText: "Complaints in each of the last 12 periods; the dark bar is the latest", objectName: "Feature sparkline" });
  text(s, "16 complaints this period · normally 10 · 9 from version 4.66", { x: ex + 0.3, y: 3.05, w: exw - 0.6, h: 0.35, fontSize: 13 });
  const quotes = [
    ["“Setting a primary device requires ID verification that fails constantly, so I am still unable to make this the primary device”", "2★ · Sep 2 · v4.66"],
    ["“I just changed my phone and I want to add my new device to the trusted devices”", "1★ · Sep 8 · v4.66"],
  ];
  quotes.forEach(([q, m], i) => {
    s.addText([
      { text: q, options: { italic: true, breakLine: true } },
      { text: m, options: { color: C.accent3, fontSize: 11 } },
    ], { isTextBox: true, x: ex + 0.3, y: 3.55 + i * 0.98, w: exw - 0.6, h: 0.92, fontSize: 13, color: C.text1, margin: 0, valign: "top", objectName: "Quote " + (i + 1) });
  });
  caption(s, "Examples from the demo (Aug 26 – Sep 22, 2026).", ex, 5.7, exw);
  band(s, "A working demo is deployed, and the Mobile product manager's feedback has been positive.", 6.1, 0.6, "Demo band");
  s.addNotes(
`TALK TRACK (about 45 s; the demo after the pitch shows this live, so keep it brief)
Here's what lands with each team: a team page showing where complaints are up against normal, and a personal email per feature, like this one, where sixteen complaints against a normal ten point straight at app version 4.66, with the customers' own words behind the number.
A working demo is deployed and the Mobile product manager's feedback has been positive. I'll walk through it live right after these slides.`);

  // 8. What we need: cards, cloud on one row and people on the other (Kevin, 2026-11-04).
  pres.addSection({ title: "Running it" });
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "Running it" });
  s.addText("What we need", { placeholder: "title" });
  const needRow = async (label, LabelIc, items, y0, withOwner) => {
    await iconCircle(s, LabelIc, M, y0, 0.38, label);
    text(s, label, { x: M + 0.5, y: y0, w: 6, h: 0.38, fontSize: 16, bold: true, color: C.accent1, valign: "middle" });
    const n = items.length, gapX = 0.2, w = (CW - (n - 1) * gapX) / n, h = 1.62, y = y0 + 0.5;
    for (let i = 0; i < n; i++) {
      const [Ic, head, detail, owner] = items[i];
      const x = M + i * (w + gapX);
      card(s, x, y, w, h, label + " card " + (i + 1));
      await iconCircle(s, Ic, x + 0.18, y + 0.18, 0.5, label + " " + (i + 1));
      text(s, head, { x: x + 0.8, y: y + 0.13, w: w - 0.92, h: 0.6, fontSize: 14, bold: true, color: C.text2, valign: "middle" });
      text(s, detail, { x: x + 0.18, y: y + 0.82, w: w - 0.3, h: withOwner ? 0.45 : 0.72, fontSize: 12 });
      if (withOwner) text(s, owner + " (to confirm)", { x: x + 0.18, y: y + 1.3, w: w - 0.3, h: 0.28, fontSize: 11, color: C.accent3 });
    }
  };
  await needRow("In our cloud (Azure or AWS)", fa.FaCloud, [
    [fa.FaServer, "Hosting", "Room to run the six pieces from the overview"],
    [fa.FaRobot, "AI service", "An approved AI to sort the reviews"],
    [fa.FaGooglePlay, "Google Play access", "So it can pick up new reviews each period"],
    [fa.FaBook, "Wiki connection", "So it can post the team pages"],
    [fa.FaPaperPlane, "Email", "A way to send email, and the OK to email staff"],
  ], 1.45, false);
  await needRow("People and approvals", fa.FaUserFriends, [
    [fa.FaSitemap, "Ownership Matrix", "Someone to keep it current as teams change", "Mobile product leadership"],
    [fa.FaSearch, "First-month check", "An analyst to review the first month's reports", "Mobile analyst team"],
    [fa.FaShieldAlt, "Compliance sign-off", "Approval to use cloud AI on public reviews", "Compliance"],
    [fa.FaFolderOpen, "A wiki space", "A home for the team pages", "Technology"],
  ], 3.75, true);
  band(s, "It's a light load. Each run is short and only reads the reviews posted since the last one.", 6.15, 0.55, "Size band");
  s.addNotes(
`DRAFT, CONFIRM WITH KEVIN: the people, owners and cloud items are drafted; Kevin sets the final asks.

TALK TRACK (about 1 min)
Here's what it takes. The whole project runs in our cloud, so first it needs room to run, sized by our cloud team. It also needs an approved AI service, access to the app's Google Play reviews, a connection to our wiki, and a way to send email to staff.
On the people side, we need someone to keep the Ownership Matrix current, an analyst to look over the first month's reports, Compliance to sign off on using cloud AI with public reviews, and a space on our wiki.
And it's a light load: each run is short and only reads the reviews posted since the last one.
IF ASKED about Google Play: today it reads the public review pages. As the app's owner, RBC could instead use Google's official Play Console API, which needs Play Console access.`);

  // 9. Next steps and thank you: the roadmap, the decision and the close on one slide (Kevin, 2026-11-04).
  pres.addSection({ title: "Next steps" });
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "Next steps" });
  s.addText("Next steps", { placeholder: "title" });
  const next = [
    ["Approve", "The project and a cloud allocation for a trial"],
    ["Set up in the cloud", "Move the demo onto RBC's Azure or AWS, connected to our wiki and email"],
    ["Load the Ownership Matrix", "Who owns which feature, team by team"],
    ["Trial with the Mobile team", "Run it for a few app releases, with an analyst checking the first month"],
  ];
  const nw = (CW - 3 * 0.3) / 4, ny = 1.95;
  s.addShape(pres.shapes.LINE, { x: M + 0.3, y: ny - 0.3, w: CW - 0.6, h: 0, line: { color: C.accent4, width: 2 }, objectName: "Timeline line" });
  next.forEach(([h, b], i) => {
    const x = M + i * (nw + 0.3);
    s.addShape(pres.shapes.OVAL, { x, y: ny - 0.6, w: 0.6, h: 0.6, fill: { color: C.accent1 }, line: { color: C.background1, width: 3 }, objectName: "Step dot " + (i + 1) });
    text(s, String(i + 1), { x, y: ny - 0.6, w: 0.6, h: 0.6, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle" });
    card(s, x, ny + 0.2, nw, 1.75, "Next step card " + (i + 1));
    text(s, h, { x: x + 0.25, y: ny + 0.35, w: nw - 0.5, h: 0.62, fontSize: 16, bold: true, color: C.text2 });
    text(s, b, { x: x + 0.25, y: ny + 0.98, w: nw - 0.5, h: 0.9, fontSize: 13 });
  });
  text(s, "If the trial goes well, we bring in more teams.", { x: M, y: 4.0, w: CW, h: 0.3, fontSize: 13, color: C.accent3 });
  band(s, "Today's ask: approval and a cloud allocation to trial Product View with the Mobile team.", 4.45, 0.6, "Decision band");
  card(s, M, 5.3, CW, 1.4, "Thank you card");
  text(s, "Thank you", { x: M + 0.35, y: 5.3, w: 3.0, h: 1.4, fontSize: 36, color: C.accent1, valign: "middle" });
  s.addShape(pres.shapes.LINE, { x: M + 3.3, y: 5.55, w: 0, h: 0.9, line: { color: C.accent2, width: 3 }, objectName: "Thank you rule" });
  s.addText([
    { text: "Every customer heard. Every team knows what to fix next.", options: { breakLine: true } },
    { text: "Up next: a live demo", options: { bold: true, color: C.text2, fontSize: 18 } },
  ], { isTextBox: true, x: M + 3.6, y: 5.3, w: 6.4, h: 1.4, fontSize: 16, color: C.text1, margin: 0, valign: "middle", paraSpaceAfter: 6, objectName: "Thank you text" });
  s.addNotes(
`DRAFT, CONFIRM WITH KEVIN: the decision line is drafted.

TALK TRACK (about 1 min)
There are four steps. First, approve the project and a cloud allocation for a trial. Second, set it up in RBC's Azure or AWS and connect it to our wiki and email. Third, load the Ownership Matrix, so it knows who owns which feature. Fourth, run a trial with the Mobile team over a few app releases, with an analyst checking the first month. If that goes well, we bring in more teams.
So my ask today is approval and a cloud allocation to trial Product View with the Mobile team.
Thank you. The goal is simple: every customer heard, and every team knowing what to fix next. Let me show you the working demo now, and I'll take questions after.

TIMING: the slides run about 10 minutes, leaving the rest of the 30-minute meeting for the demo and questions.`);

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
}

build().catch((e) => { console.error(e); process.exit(1); });
