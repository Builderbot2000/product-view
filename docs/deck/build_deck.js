// Build docs/deck/product-view-pitch.pptx: the proposal deck for senior managers (pitch-deck-brief.md,
// revisions of 2026-10-23). Slide sources live in out/deck/sources.md, not in the deck.
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
// RBC Energy Lines (guide section 4): nested lines that come down the right edge, round the
// shield-like corner and sweep left, rising gently to the right. Drawn as live shapes; colours from
// the primary palette (the guide's outer light-blue line is approximated by Tint 1 at 45% transparency).
function energyLines(slide, { x, yCorner, yLeft, r, gap }) {
  const lines = [[HEX.dk2, 0], [HEX.accent2, 0], [HEX.lt1, 0], [HEX.accent1, 45]];
  lines.forEach(([color, transparency], i) => {
    const o = i * gap, X = x + o, yC = yCorner + o, yL = yLeft + o, rr = r + o;
    slide.addShape(pres.shapes.CUSTOM_GEOMETRY, {
      x: 0, y: 0, w: W, h: 7.5, objectName: "Energy line " + (i + 1),
      fill: { type: "none" }, line: { color, width: 4.5, transparency },
      points: [
        { x: 0, y: yL },
        { x: X - rr, y: yC, curve: { type: "cubic", x1: X * 0.45, y1: yL, x2: X - rr - 2.5, y2: yC } },
        { x: X, y: yC - rr, curve: { type: "cubic", x1: X - rr * 0.45, y1: yC, x2: X, y2: yC - rr * 0.55 } },
        { x: X, y: 0 },
      ],
    });
  });
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
    { text: "Customer reviews of the RBC Mobile app, sorted by feature and delivered to the team that owns it", options: { breakLine: true } },
    { text: "Internal proposal · October 2026 · Kevin Tang", options: { fontSize: 16, color: C.text1 } },
  ], { placeholder: "subtitle" });
  energyLines(s, { x: 12.05, yCorner: 5.45, yLeft: 5.95, r: 1.1, gap: 0.12 });
  s.addNotes(
`TALK TRACK (about 30 s)
I'm here to propose a project called Product View. It takes the reviews customers leave for the RBC Mobile app on Google Play, sorts them by the app feature they're about, and sends each team a weekly report on just the features it owns. I'll cover the need, what the product team asked for, how it works, and what it takes to run it at RBC.`);

  // 2. The need
  pres.addSection({ title: "The need" });
  s = pres.addSlide({ masterName: "PV Text and Visual", sectionTitle: "The need" });
  s.addText("Today, reviews reach the team one at a time", { placeholder: "title" });
  s.addText([
    { text: "Customers rate the RBC Mobile app on Google Play and often explain why in a few lines.", options: { breakLine: true } },
    { text: "Each new review is posted on its own into a Slack channel.", options: { breakLine: true } },
    { text: "Nobody can see which features are hurting, which problems are growing, or how many customers each one affects.", options: { breakLine: true } },
    { text: "In October 2024, 1,663 complaints arrived as 1,663 separate messages.", options: { bold: true } },
  ], { placeholder: "body" });
  const stats = [
    ["21,506", "written reviews by Canadian customers since 2011"],
    ["13,930", "of them rated 1 to 3 stars out of 5"],
    ["7.4%", "written in French (1,335 reviews)"],
  ];
  stats.forEach(([n, l], i) => {
    const y = 1.65 + i * 1.7;
    card(s, 7.0, y, 5.73, 1.4, "Stat card " + (i + 1));
    text(s, n, { x: 7.3, y: y + 0.2, w: 2.5, h: 1.0, fontSize: 40, bold: true, color: C.accent1, valign: "middle", objectName: "Stat number " + (i + 1) });
    text(s, l, { x: 9.8, y: y + 0.2, w: 2.75, h: 1.0, fontSize: 16, valign: "middle", objectName: "Stat label " + (i + 1) });
  });
  s.addNotes(
`TALK TRACK (about 1 min)
When customers rate our app on Google Play, many of them write a few lines saying why. Today those reviews reach the Mobile team one at a time: each new review is posted on its own into a Slack channel. That's fine for reading one review, but it can't tell a team how its part of the app is doing: which features are hurting, which problems are growing, how many customers each one affects. And there are a lot of them: over twenty-one thousand written reviews from Canadian customers since 2011, nearly fourteen thousand of them 1 to 3 stars, and about one in fourteen in French. When things go wrong it gets worse: in October 2024, 1,663 complaints arrived in one month, as 1,663 separate messages.`);

  // 3. What the product manager asked for
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The need" });
  s.addText("What the Mobile product manager asked for", { placeholder: "title" });
  card(s, M, 1.6, 4.6, 3.7, "Ask card", C.accent1);
  await iconCircle(s, fa.FaEnvelopeOpenText, M + 0.35, 1.9, 0.85, "Ask", C.background1, HEX.accent1);
  text(s, "A weekly email for each team, on just the features it owns", { x: M + 0.35, y: 2.95, w: 3.9, h: 1.4, fontSize: 22, bold: true, color: C.background1 });
  text(s, "What customers said, how much, and whether it's getting better or worse", { x: M + 0.35, y: 4.35, w: 3.9, h: 0.8, fontSize: 15, color: C.background1 });
  const gets = [
    [fa.FaSearch, "Analysts", "A head start: the numbers and quotes for their own reports"],
    [fa.FaClipboardList, "Feature owners", "Just their features, in their inbox, every week"],
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
  band(s, "Inspired by RBC's push to put AI to work, Product View is a proposal to deliver exactly that.", 5.65, 0.75, "Inspiration band");
  s.addNotes(
`TALK TRACK (about 1.5 min)
The Mobile product manager asked for something simple: a weekly email for each team, covering only the features that team owns. What customers said, how much of it there was, and whether it's getting better or worse.
That helps everyone around the app. Analysts get a head start on their own reports: the numbers and the quotes. Feature owners get just their features, in their inbox, every week. Engineering can see which app release started a problem. Customer support sees what customers raise, in their own words. It doesn't replace analysts; it gives them better evidence.
RBC's push to put AI to work inspired this project. Product View is my proposal to deliver what the product manager asked for.`);

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
  caption(s, "Made-up names, for illustration. Teams set the feature list; the tool never invents its own.", M, yy - 0.05, 8.1);
  const musts = [
    ["Your features only", "Each owner sees just the features they own"],
    ["Public reviews only", "Only what customers posted on Google Play"],
    ["Data stays inside RBC", "No outside AI services"],
    ["Numbers you can check", "Counts of real reviews, quotes that link back"],
    ["Runs by itself", "Every week, with nobody starting it"],
  ];
  musts.forEach(([h, b], i) => {
    const y = 1.55 + i * 0.98, x = 9.15;
    marker(s, x, y + 0.08, "Marker " + (i + 1));
    text(s, h, { x: x + 0.4, y, w: 3.18, h: 0.38, fontSize: 16, bold: true, color: C.text2 });
    text(s, b, { x: x + 0.4, y: y + 0.38, w: 3.18, h: 0.5, fontSize: 13 });
  });
  s.addNotes(
`TALK TRACK (about 1.5 min)
Here's what it has to do. It starts from one list: the teams, the people in each team, and the specific app features each person owns. What you see is made up, to show the shape; the real list comes from our internal team directory and stays confidential. The teams set the list; the tool never invents its own features, so "change password or PIN" means the same thing every week.
And it has to fit the bank: each owner sees only their own features; it reads only what customers have posted publicly on Google Play; the data stays inside RBC, with no outside AI services; every number is a count of real reviews and every quote links back to the review it came from; and it runs by itself every week.`);

  // 5. How it works
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The proposal" });
  s.addText("How it works: from app store to inbox", { placeholder: "title" });
  const steps = [
    [fa.FaCloudDownloadAlt, "Collect", "Gathers every new Google Play review each week"],
    [fa.FaLanguage, "Translate", "Turns French reviews into English, so one team can read them all"],
    [fa.FaTags, "Sort", "AI reads each review and matches it to the features on the list, like “change password or PIN”"],
    [fa.FaEnvelope, "Share", "Posts a page for each team on our wiki and emails each owner their report"],
  ];
  const sw = 2.62, gap = (CW - 4 * sw) / 3;
  for (let i = 0; i < steps.length; i++) {
    const [Ic, head, body] = steps[i];
    const x = M + i * (sw + gap), y = 1.75;
    card(s, x, y, sw, 3.7, "Step card " + (i + 1));
    await iconCircle(s, Ic, x + 0.3, y + 0.35, 0.95, "Step " + (i + 1));
    text(s, "Step " + (i + 1), { x: x + 0.3, y: y + 1.5, w: sw - 0.6, h: 0.3, fontSize: 12, color: C.accent3, bold: true });
    text(s, head, { x: x + 0.3, y: y + 1.85, w: sw - 0.6, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
    text(s, body, { x: x + 0.3, y: y + 2.4, w: sw - 0.6, h: 1.2, fontSize: 15 });
    if (i < 3) arrow(s, x + sw + gap / 2 - 0.17, y + 0.65, "Arrow " + (i + 1));
  }
  band(s, "It repeats every week on its own. Nobody has to start it.", 5.8, 0.6, "Weekly band");
  s.addNotes(
`TALK TRACK (about 1 min)
Here's the whole thing in four steps. Each week, it gathers every new review from Google Play. It translates the French ones into English, so one team can read them all. Then the AI reads each review and matches it to the features on the list, things as specific as "change password or PIN". A review can match several features, or none, and the ones that match none are still counted, so we can see if the list is missing something. Finally, it posts a page for each team on our internal wiki, Confluence, and emails each owner their own report. And it repeats every week without anyone starting it.`);

  // 6. How a report is put together
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The proposal" });
  s.addText("How each report is put together", { placeholder: "title" });
  text(s, "For every feature, every week", { x: M, y: 1.55, w: 6.6, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
  const recipe = [
    ["Count", "How many customers complained about it in the last four weeks"],
    ["Compare", "Against a normal four weeks, so rising and new problems stand out"],
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
    "The feature list stays the same, so trends mean the same thing week after week",
  ]), { isTextBox: true, x: tx + 0.4, y: 2.9, w: tw - 0.8, h: 3.4, fontSize: 16, color: C.text1, margin: 0, valign: "top", paraSpaceAfter: 12, objectName: "Trust list" });
  s.addNotes(
`TALK TRACK (about 1 min)
Once reviews are sorted, building a report is plain arithmetic. For every feature, every week: count how many customers complained about it in the last four weeks; compare that with a normal four weeks, so anything rising or new stands out; trace which app versions the complaints came from, so a bad release shows up; and show customers' own words, with the star rating, date and version.
That's why the numbers can be trusted. The AI has one narrow job, deciding which feature a review is about. Every number is a count of real reviews, and every quote links back to the review it came from, so anyone can check it. And because the feature list stays the same, a trend means the same thing from one week to the next.`);

  // 7. What teams receive
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "The proposal" });
  s.addText("What teams receive", { placeholder: "title" });
  const lw = 6.1;
  text(s, "Team page: the big picture", { x: M, y: 1.5, w: lw, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  const ar = imgFit(path.join(ASSETS, "hub-areas.png"), lw, 3.4);
  s.addImage({ path: path.join(ASSETS, "hub-areas.png"), x: M, y: 2.05, w: ar.w, h: ar.h, altText: "Chart from the demo: complaints by product area in the latest four weeks against normal, with the areas that rose flagged", objectName: "Team page chart" });
  caption(s, "Complaints by product area, latest four weeks vs. normal. Red = up.", M, 2.05 + ar.h + 0.1, lw);
  const ex = M + lw + 0.4, exw = W - M - ex;
  text(s, "Personal email: your features", { x: ex, y: 1.5, w: exw, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  card(s, ex, 2.05, exw, 3.55, "Example card", C.background1);
  outline(s, ex, 2.05, exw, 3.55, "Example card");
  text(s, "Can't confirm a new phone as a trusted device", { x: ex + 0.3, y: 2.25, w: exw - 2.6, h: 0.75, fontSize: 16, bold: true, color: C.text2 });
  const sp = imgFit(path.join(ASSETS, "spark-2fa.png"), 1.9, 0.45);
  s.addImage({ path: path.join(ASSETS, "spark-2fa.png"), x: ex + exw - 0.3 - sp.w, y: 2.3, w: sp.w, h: sp.h, altText: "Complaints in each of the last 12 four-week periods; the dark bar is the latest", objectName: "Feature sparkline" });
  text(s, "16 complaints in four weeks · normally 10 · 9 from version 4.66", { x: ex + 0.3, y: 3.05, w: exw - 0.6, h: 0.35, fontSize: 13 });
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
`TALK TRACK (about 1.5 min)
Here's what lands with each team. On the left, the team page: complaints by area of the app over the latest four weeks, against what's normal. Red means up, so a lead sees at a glance where to look.
On the right, one section of a personal email report: one feature, sixteen complaints in four weeks against a normal ten, nine of them from app version 4.66, so the team can see it started with that release, and then the customers' own words behind the number.
Both are real examples from the demo. A working demo is deployed, and the Mobile product manager's feedback has been positive.`);

  // 8. Running it on Azure
  pres.addSection({ title: "Running it" });
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "Running it" });
  s.addText("Running it on Azure", { placeholder: "title" });
  const flow = [
    [fa.FaMobileAlt, "Google Play", "Public reviews"],
    [fa.FaCloud, "RBC's Azure", "The weekly run"],
    [fa.FaUsers, "Our teams", "Wiki pages and emails"],
  ];
  const fw = 3.4, fgap = (CW - 3 * fw) / 2;
  for (let i = 0; i < flow.length; i++) {
    const [Ic, h, b] = flow[i];
    const x = M + i * (fw + fgap), y = 1.5;
    card(s, x, y, fw, 1.0, "Flow card " + (i + 1), i === 1 ? C.accent1 : C.background2);
    await iconCircle(s, Ic, x + 0.22, y + 0.2, 0.6, "Flow " + (i + 1), i === 1 ? C.background1 : C.accent1, i === 1 ? HEX.accent1 : HEX.lt1);
    text(s, h, { x: x + 1.0, y: y + 0.14, w: fw - 1.15, h: 0.4, fontSize: 17, bold: true, color: i === 1 ? C.background1 : C.text2 });
    text(s, b, { x: x + 1.0, y: y + 0.52, w: fw - 1.15, h: 0.35, fontSize: 13, color: i === 1 ? C.background1 : C.text1 });
    if (i < 2) arrow(s, x + fw + fgap / 2 - 0.17, y + 0.33, "Flow arrow " + (i + 1));
  }
  const svc = [
    [fa.FaCalendarCheck, "Runs it every week", "Azure Container Apps (scheduled job)"],
    [fa.FaRobot, "The AI that sorts reviews", "Microsoft Foundry (Azure OpenAI models)"],
    [fa.FaDatabase, "Stores the reviews", "Azure Files"],
    [fa.FaKey, "Keeps passwords safe", "Azure Key Vault"],
    [fa.FaPaperPlane, "Sends the emails", "Azure Communication Services Email"],
    [fa.FaHeartbeat, "Hosts and monitors it", "Azure Container Registry · Azure Monitor"],
  ];
  const sw3 = (CW - 2 * 0.3) / 3, sh3 = 1.3;
  for (let i = 0; i < svc.length; i++) {
    const [Ic, h, b] = svc[i];
    const x = M + (i % 3) * (sw3 + 0.3), y = 2.85 + Math.floor(i / 3) * (sh3 + 0.25);
    card(s, x, y, sw3, sh3, "Service card " + (i + 1));
    await iconCircle(s, Ic, x + 0.25, y + 0.3, 0.62, "Service " + (i + 1));
    text(s, h, { x: x + 1.05, y: y + 0.22, w: sw3 - 1.25, h: 0.45, fontSize: 15, bold: true, color: C.text2 });
    text(s, b, { x: x + 1.05, y: y + 0.68, w: sw3 - 1.25, h: 0.5, fontSize: 12, color: C.accent3 });
  }
  band(s, "Everything stays inside RBC's Azure environment. Team pages stay on our existing wiki.", 5.95, 0.6, "Azure band");
  s.addNotes(
`TALK TRACK (about 1.5 min)
To run this properly it needs a home at RBC, and Azure fits it well. Reviews come in from Google Play, the weekly run happens inside RBC's Azure, and the results go out to our teams as wiki pages and emails.
Six pieces of Azure do the work. Azure Container Apps runs it every week on a timer and only charges while it runs. Microsoft Foundry provides the AI that sorts reviews, inside our Azure environment rather than through an outside service. Azure Files keeps the reviews between runs. Key Vault keeps the passwords for the wiki and email safe. Azure Communication Services sends the emails. And Container Registry and Azure Monitor store the app and flag a run that fails.
Everything stays inside RBC's Azure environment, and the team pages stay on the wiki we already use.

IF ASKED: Microsoft Foundry was formerly Azure AI Foundry; Microsoft states prompts and outputs are not used to train its models. If RBC staff email runs on Microsoft 365, sending from a shared mailbox may replace Communication Services; IT's call. The workload is small: one short weekly run over a few dozen new reviews.`);

  // 9. What we need
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "Running it" });
  s.addText("What we need", { placeholder: "title" });
  const colW = (CW - 0.4) / 2;
  card(s, M, 1.55, colW, 4.35, "Azure card");
  await iconCircle(s, fa.FaCloud, M + 0.35, 1.8, 0.7, "Azure");
  text(s, "On Azure", { x: M + 1.25, y: 1.8, w: colW - 1.5, h: 0.7, fontSize: 20, bold: true, color: C.text2, valign: "middle" });
  s.addText(bullets([
    "An Azure allocation for Product View, sized by our cloud team",
    "Access to Azure OpenAI models through Microsoft Foundry",
    "The services on the previous slide",
    "Permission to send email to staff",
  ]), { isTextBox: true, x: M + 0.4, y: 2.75, w: colW - 0.8, h: 3.0, fontSize: 16, color: C.text1, margin: 0, valign: "top", paraSpaceAfter: 12, objectName: "Azure list" });
  const px = M + colW + 0.4;
  card(s, px, 1.55, colW, 4.35, "People card");
  await iconCircle(s, fa.FaUserFriends, px + 0.35, 1.8, 0.7, "People");
  text(s, "People and approvals", { x: px + 1.25, y: 1.8, w: colW - 1.5, h: 0.7, fontSize: 20, bold: true, color: C.text2, valign: "middle" });
  const people = [
    ["The real feature list, kept up to date", "Mobile product leadership"],
    ["An analyst to check the first month's reports", "Mobile analyst team"],
    ["Sign-off to use Azure AI on public reviews", "Compliance"],
    ["A space on our wiki", "Technology"],
  ];
  people.forEach(([h, o], i) => {
    const y = 2.75 + i * 0.75;
    text(s, h, { x: px + 0.4, y, w: colW - 0.8, h: 0.4, fontSize: 15, bold: true, color: C.text1 });
    text(s, o + " (to confirm)", { x: px + 0.4, y: y + 0.36, w: colW - 0.8, h: 0.3, fontSize: 12, color: C.accent3 });
  });
  band(s, "The workload is small: one short run a week, over a few dozen new reviews.", 6.15, 0.55, "Size band");
  s.addNotes(
`DRAFT, CONFIRM WITH KEVIN: the people, owners and Azure items are drafted; Kevin sets the final asks.

TALK TRACK (about 1.5 min)
Here's what it takes. On Azure: an allocation for Product View, sized by our cloud team; access to Azure OpenAI models through Microsoft Foundry; the services on the previous slide; and permission to send email to staff.
From people: the real list of teams, owners and features, and someone to keep it current, likely Mobile product leadership. An analyst to check the first month's reports, so quality is judged by the people who'll use them. Compliance sign-off to use Azure AI on public reviews. And a space on our wiki.
The workload is small: one short run a week over a few dozen new reviews.`);

  // 10. Next steps and the decision
  pres.addSection({ title: "Next steps" });
  s = pres.addSlide({ masterName: "PV Title Only", sectionTitle: "Next steps" });
  s.addText("Next steps", { placeholder: "title" });
  const next = [
    ["Approve", "The project and an Azure allocation for a trial"],
    ["Set up on Azure", "Move the demo onto RBC's Azure, connected to our wiki and email"],
    ["Load the real list", "Our teams, owners and features"],
    ["Trial with the Mobile team", "A few app releases, with an analyst checking the first month"],
  ];
  const nw = (CW - 3 * 0.3) / 4, ny = 2.35;
  s.addShape(pres.shapes.LINE, { x: M + 0.35, y: ny - 0.35, w: CW - 0.7, h: 0, line: { color: C.accent4, width: 2 }, objectName: "Timeline line" });
  next.forEach(([h, b], i) => {
    const x = M + i * (nw + 0.3);
    s.addShape(pres.shapes.OVAL, { x, y: ny - 0.7, w: 0.7, h: 0.7, fill: { color: C.accent1 }, line: { color: C.background1, width: 3 }, objectName: "Step dot " + (i + 1) });
    text(s, String(i + 1), { x, y: ny - 0.7, w: 0.7, h: 0.7, fontSize: 20, bold: true, color: C.background1, align: "center", valign: "middle" });
    card(s, x, ny + 0.3, nw, 2.5, "Next step card " + (i + 1));
    text(s, h, { x: x + 0.3, y: ny + 0.55, w: nw - 0.6, h: 0.8, fontSize: 18, bold: true, color: C.text2 });
    text(s, b, { x: x + 0.3, y: ny + 1.35, w: nw - 0.6, h: 1.35, fontSize: 15 });
  });
  text(s, "Then, if the trial goes well: more teams.", { x: M, y: 5.4, w: CW, h: 0.35, fontSize: 14, color: C.accent3 });
  band(s, "Today: approve Product View and an Azure allocation for a trial with the Mobile team.", 6.0, 0.7, "Decision band");
  s.addNotes(
`DRAFT, CONFIRM WITH KEVIN: the decision line is drafted.

TALK TRACK (about 1 min)
Four steps. First, approve the project and an Azure allocation for a trial. Second, set it up on RBC's Azure, connected to our wiki and email. Third, load the real list of teams, owners and features. Fourth, a trial with the Mobile team over a few app releases, with an analyst checking the first month. If the trial goes well, we extend it to more teams.
So what I'm asking for today: approval for Product View, and an Azure allocation for a trial with the Mobile team.`);

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
}

build().catch((e) => { console.error(e); process.exit(1); });
