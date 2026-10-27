import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const out = path.dirname(fileURLToPath(import.meta.url));
const C = { ink: '#203b30', muted: '#65786e', line: '#b4c8bd', green: '#245c45', teal: '#147f82', blue: '#315f92', amber: '#a46a1e', red: '#a54545', paper: '#f5f8f6' };
const esc = value => String(value).replace(/[&<>\"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const text = (x, y, value, size = 15, color = C.ink, weight = 400) => `<text x="${x}" y="${y}" fill="${color}" font-size="${size}" font-weight="${weight}">${esc(value)}</text>`;
function node(x, y, w, title, lines = [], tone = 'green', h = 94, dark = false) {
  const color = C[tone];
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6" fill="${dark ? color : '#fff'}" stroke="${dark ? color : '#d6e2db'}"/>` +
    `<rect x="${x}" y="${y}" width="4" height="${h}" rx="2" fill="${color}"/>` +
    text(x + 18, y + 30, title, 18, dark ? '#fff' : C.ink, 700) +
    lines.map((line, i) => text(x + 18, y + 54 + i * 19, line, 13.5, dark ? '#e4eee8' : C.muted)).join('');
}
const edge = (points, color = C.line, dashed = false) => `<path d="${points}" fill="none" stroke="${color}" stroke-width="1.8" ${dashed ? 'stroke-dasharray="5 4"' : ''} marker-end="url(#arrow)"/>`;
const rule = y => `<path d="M32 ${y}H1088" stroke="#d9e4dd"/>`;
const band = (x, y, w, label, detail, tone = 'green') => `<rect x="${x}" y="${y}" width="${w}" height="62" rx="5" fill="#fff" stroke="#d6e2db"/>` + text(x + 16, y + 25, label, 14, C[tone], 700) + text(x + 16, y + 46, detail, 13, C.muted);
const diagrams = [];
async function save(file, title, subtitle, height, content, note = 'Architecture / policy diagram. Not a live status display.') {
  const body = `<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="${height}" viewBox="0 0 1120 ${height}" role="img" aria-labelledby="title desc"><title id="title">${esc(title)}</title><desc id="desc">${esc(subtitle)}</desc><defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7Z" fill="${C.line}"/></marker></defs><rect width="1120" height="${height}" rx="8" fill="${C.paper}"/><g font-family="Arial, Helvetica, sans-serif">${text(32, 38, title, 25, C.ink, 700)}${text(32, 65, subtitle, 14, C.muted)}${rule(88)}${content}${text(32, height - 20, note, 12, C.muted)}</g></svg>\n`;
  await fs.writeFile(path.join(out, file), body);
  diagrams.push({ file, title, kind: 'architecture', liveStatus: false });
}

let b = '';
const rows = [
  ['HA', 'green', ['HA events', 'state_changed / Recorder'], ['Features', '10m / 30m / 1h / 2h'], ['Baseline + IF / AE', 'Repetition / routine gates'], ['MQTT decision', 'repetitive-ai']],
  ['mmWave', 'blue', ['Target events', 'Position / tracking quality'], ['Trajectory features', 'Shape / personal history'], ['Temporal evidence', 'Persistence / quality gates'], ['MQTT decision', 'wandering-ai']],
  ['Voice', 'teal', ['Consent + WAV', 'Metadata / format checks'], ['Piper training', 'GPU fine-tuning'], ['Export + validate', 'ONNX / JSON / sample WAV'], ['Model release', 'API / R2 to Pi 5']],
];
rows.forEach((row, i) => {
  const y = 124 + i * 132;
  b += text(32, y + 45, row[0], 17, C[row[1]], 700);
  row.slice(2).forEach((step, j) => {
    const x = 150 + j * 238;
    b += node(x, y, 224, step[0], [step[1]], row[1], 86);
    if (j < 3) b += edge(`M${x + 224} ${y + 43}H${x + 238}`);
  });
});
await save('ai-pipelines.svg', 'Three pipelines, separate responsibilities', 'Behavior models publish decisions. Voice training produces a deployable model.', 548, b);

function chain(labels, y = 144, tone = 'green') {
  const gap = 18;
  const w = (1056 - gap * (labels.length - 1)) / labels.length;
  let result = '';
  labels.forEach((label, i) => {
    const x = 32 + i * (w + gap);
    result += node(x, y, w, label[0], label.slice(1), tone, 100);
    if (i < labels.length - 1) result += edge(`M${x + w} ${y + 50}H${x + w + gap}`);
  });
  return result;
}
b = chain([['Collect', 'Source + household', 'Coverage metadata'], ['Eligibility', '30 eligible days', 'Normal candidates'], ['Train IF / AE', 'Time-ordered splits', 'Calibration / test'], ['Validate', 'Quality gate', 'Compatibility'], ['Activate', 'Versioned bundle', 'Atomic pointer']], 140);
b += edge('M775 240V282H536V316', C.red, true) + band(344, 316, 384, 'VALIDATION FAILURE / MODEL UNAVAILABLE', 'Retain a compatible current model or use Baseline.', 'red');
b += band(32, 410, 510, 'SHADOW', 'Record model scores without changing the rule decision.', 'blue') + band(560, 410, 528, 'HYBRID', 'Use validated scores with observed repetition and policy gates.');
await save('learning-lifecycle.svg', 'From observation to a versioned model', 'The calendar alone does not trigger learning. Data eligibility and validation are required.', 520, b);

b = node(32, 136, 256, 'Pi 5 / Central', ['Decision Event', 'Device Token'], 'green') + node(32, 284, 256, 'Pi 4 / Camera', ['Door-event photo', 'Device Token'], 'blue');
b += node(430, 208, 264, 'FastAPI / Render', ['Authentication / event history', 'Settings / voice jobs'], 'green', 112, true);
b += node(820, 136, 268, 'Flutter Guardian', ['REST / WebSocket / Push', 'Settings / recording'], 'teal') + node(820, 356, 268, 'GPU Worker', ['Leased training jobs', 'Worker Token'], 'blue');
b += node(430, 392, 264, 'R2 / private storage', ['Photos / WAV / model objects'], 'teal', 86);
b += edge('M288 183H358V242H430') + edge('M288 331H358V286H430') + edge('M694 242H752V183H820') + edge('M820 211H778V282H694') + edge('M562 320V392');
b += edge('M694 300H748V386H820') + edge('M694 418H820') + edge('M820 440H694');
b += text(756, 343, 'Jobs', 13, C.blue) + text(722, 124, 'App Token', 13, C.teal) + text(32, 443, 'Credentials stay in their own trust boundary.', 14, C.muted);
await save('apps-connections.svg', 'The app and API connect people, devices and jobs', 'Inference stays on the AI side; approved device actions stay on the edge side.', 530, b);

const actors = [['Central', 130], ['API', 410], ['Push provider', 690], ['Guardian', 970]];
b = actors.map(([label, x]) => node(x - 96, 116, 192, label, [], 'green', 52) + `<path d="M${x} 168V500" stroke="#c9d7cf" stroke-dasharray="4 5"/>`).join('');
const messages = [[130, 410, 211, '1. Decision Event / Device Token'], [410, 970, 286, '3. WebSocket update (connected app)'], [410, 690, 352, '4. FCM / Web Push request'], [690, 970, 411, '5. OS / browser notification'], [970, 410, 478, '6. Read-state request / App Token']];
messages.forEach(([from, to, y, label]) => { b += edge(`M${from} ${y}H${to}`, C.blue) + text(Math.min(from, to) + 10, y - 12, label, 13, C.ink); });
b += text(424, 249, '2. Validate / deduplicate / persist', 13, C.green, 700);
await save('notification-sequence.svg', 'One event, several acknowledgements', 'Broker receipt, API acceptance and visible phone delivery are different checkpoints.', 550, b, 'Sequence overview. Push delivery requires credentials, permissions and a registered device.');

b = node(32, 126, 328, 'Behavior Inference v1', ['source: repetitive-ai / wandering-ai', 'behavior / risk_level / risk_score', 'inference_status / evidence'], 'green', 136);
b += node(396, 126, 328, 'Central Decision Event', ['source: central-atlas-app', 'decision / risk_level / actions', 'event_id / occurred_at'], 'blue', 136);
b += node(760, 126, 328, 'App Alert', ['Guardian-facing content', 'History / unread state', 'Delivery and display are separate'], 'teal', 136);
b += edge('M360 194H396') + edge('M724 194H760');
b += band(32, 306, 510, 'IDENTITY + TIME', 'contract_version / event_id / patient_id / device_id / UTC') + band(560, 306, 528, 'UNKNOWN IS EXPLICIT', 'Non-ok inference: unknown behavior + unknown risk + null score.', 'amber');
await save('contract-map.svg', 'A shared meaning, not just valid JSON', 'The AI contract and Central Event are different messages with different responsibilities.', 424, b);

b = chain([['JSON', 'Parse / field types'], ['Schema', 'Required fields', 'Enums / ranges'], ['Source / time', 'Topic agreement', 'UTC / freshness'], ['Event ID', 'Duplicate / conflict'], ['Action policy', 'Enabled / risk', 'Cooldown']], 142);
[130, 340, 550, 760].forEach(x => { b += `<path d="M${x} 242V286" fill="none" stroke="${C.red}" stroke-dasharray="4 4"/>`; });
b += `<path d="M130 286H760" stroke="${C.red}"/>` + edge('M550 286V322', C.red, true);
b += band(320, 322, 500, 'INVALID INPUT: NO DEVICE ACTION', 'Reject or audit with a reason; do not repair it into a normal event.', 'red');
await save('validation-gates.svg', 'Validate first, route second', 'Schema correctness does not replace event identity, timing or execution policy checks.', 444, b);

b = node(32, 232, 228, 'Repository source', ['Reviewed source manifest', 'No device credentials'], 'green', 108, true);
const devices = [['Pi 3 bundle', ['Relay / sensor contracts'], 126, 'blue'], ['Pi 4 bundle', ['Camera / upload settings'], 266, 'teal'], ['Pi 5 bundle', ['Central / AI / output settings'], 406, 'green']];
devices.forEach(([label, lines, y, tone]) => {
  b += node(390, y, 310, label, lines, tone, 86) + edge(`M260 286H322V${y + 43}H390`);
  b += node(804, y, 284, 'Target preparation', [y === 406 ? 'SDK / Docker / models / services' : y === 266 ? 'Camera / Docker / permissions' : 'Serial / user / SSH / FIFO'], tone, 86) + edge(`M700 ${y + 43}H804`);
});
await save('device-bundles.svg', 'One source tree, three device bundles', 'Source archives are not preinstalled binaries, signed packages or a completed deployment.', 556, b);

b = chain([['Backup', 'Model / DB / config'], ['Verify', 'Source manifest'], ['Build', 'SDK / Docker / APK'], ['Configure', 'IDs / credentials'], ['Install', 'Files / services'], ['E2E', 'Input to output']], 144);
b += band(32, 304, 510, 'SOURCE ARCHIVE', 'Declared source and settings + BUNDLE.sha256.', 'blue') + band(560, 304, 528, 'RUNTIME ARTIFACTS', 'Central binary / .ipk / APK / ONNX need separate preparation.', 'amber');
await save('deployment-stages.svg', 'Deployment is a sequence of explicit steps', 'A Git push or an archive checksum is not a device execution test.', 416, b);

b = '';
const evidence = [['Code', ['Implementation and contracts', 'What exists in this version'], 'green'], ['Automated checks', ['Unit / regression / build', 'What the selected run checks'], 'blue'], ['Recorded evidence', ['Data origin / metrics / reports', 'What a stored experiment supports'], 'teal'], ['Device E2E', ['Sensors / output / app display', 'What a real device run proves'], 'amber']];
evidence.forEach(([label, lines, tone], i) => {
  b += node(32 + i * 270, 138, 246, label, lines, tone, 128);
  if (i < 3) b += edge(`M${278 + i * 270} 202H${302 + i * 270}`);
});
b += band(32, 318, 1056, 'TRACE EVERY CLAIM', 'Code version + data origin + command + result file + untested scope. A later layer is not proved by an earlier one.');
await save('evidence-map.svg', 'Read evidence in layers', 'Implementation, saved experiments and current hardware behavior answer different questions.', 428, b);

b = chain([['MQTT', 'Two behavior topics'], ['Validate', 'Contract / identity', 'Freshness'], ['Deduplicate', 'event_id / conflict'], ['Action Router', 'Risk / enable flags', 'Cooldown']], 132);
b += node(32, 310, 314, 'Audit / suppressed', ['Unknown, rejected or blocked', 'Do not execute appliance actions'], 'amber', 106);
b += node(394, 310, 314, 'Local guidance', ['Piper TTS / approved devices', 'Favorite music after guidance'], 'green', 106);
b += node(756, 310, 332, 'Outbox / API', ['Persistent pending delivery', 'Guardian history / notification'], 'blue', 106);
b += edge('M910 232V266H550V310') + edge('M964 232V266H922V310') + edge('M420 232V266H190V310', C.amber, true);
await save('central-routing.svg', 'Central is the execution boundary', 'A model decision becomes an output plan only after validation and routing policy.', 472, b);

b = chain([['Download', 'ONNX + JSON'], ['Verify', 'Size / SHA-256'], ['Validate', 'Config / artifacts'], ['Smoke test', 'Local synthesis'], ['Switch', 'Active model']], 146);
b += edge('M552 246V304', C.red, true) + band(312, 318, 500, 'FAILURE: KEEP THE CURRENT MODEL', 'A partial download or failed synthesis must not replace the active voice.', 'red');
await save('model-release.svg', 'A downloaded model is not yet an active model', 'The Pi updater checks the release before changing the model used by Piper.', 436, b);

b = chain([['Central approval', 'Action Router'], ['Guidance', 'TTS / devices'], ['Music request', 'Separate job'], ['API selection', 'Device Token', 'Current favorites'], ['Pi player', 'Validated video_id']], 142);
b += band(32, 306, 510, 'FAILURE ISOLATION', 'Empty list / auth / network / player error: skip music only.', 'amber') + band(560, 306, 528, 'MUSIC COOLDOWN', 'Independent from behavior alert cooldown; default 300 seconds.', 'blue');
await save('favorite-music.svg', 'Favorite music is an additional output path', 'Selection comes from the current app list; request logs do not prove audible playback.', 418, b);

b = chain([['Guardian', 'Save home region'], ['Device API', 'Device Token', 'Read nx / ny'], ['Environment', 'KMA weather', 'HA sun.sun'], ['Lighting rule', 'Brightness', 'Color temperature'], ['HA light', 'Configured entity']], 140);
b += band(32, 306, 510, 'RENDER MODE FAILURE', 'Stop this lighting update. Do not silently reuse a legacy region.', 'red') + band(560, 306, 528, 'READ-ONLY CHECK', '--check-location verifies region lookup without changing the light.', 'blue');
await save('weather-light.svg', 'Region settings connect the app to lighting', 'Home location, device authentication and HA light identity must agree.', 420, b);

b = text(48, 126, 'WORKFLOW', 12, C.muted, 700) + text(410, 126, 'CHECKS', 12, C.muted, 700) + text(830, 126, 'RUN / OUTPUT', 12, C.muted, 700);
const workflows = [
  ['HA report', 'Report data / regression / optimized Python', 'PR / main / manual'],
  ['Apps + API', 'API tests / Flutter analyze + test + build', 'PR / main / manual'],
  ['Voice', 'Worker / pipeline / updater / config', 'Related push / PR'],
  ['Favorite music', 'Mock player / routing / shell syntax', 'PR / main / manual'],
  ['Android test APK', 'Private config / Flutter / APK + checksum', 'Manual artifact'],
];
workflows.forEach((row, i) => {
  const y = 146 + i * 66;
  b += `<rect x="32" y="${y}" width="1056" height="54" rx="4" fill="${i % 2 ? '#edf3f0' : '#fff'}"/>` + text(48, y + 32, row[0], 17, C.ink, 700) + text(410, y + 32, row[1], 14, C.muted) + text(830, y + 32, row[2], 14, C.green);
});
await save('ci-map.svg', 'Checks are scoped to the component that changed', 'Path filters decide which workflow runs. A workflow definition is not a green result.', 530, b);

b = chain([['Manual trigger', 'workflow_dispatch'], ['Private config', 'Client Firebase', 'App Token'], ['Source checks', 'Analyze / test'], ['Build APK', 'Team test signing'], ['Artifact', 'APK + SHA-256', '3-day retention']], 144);
b += band(32, 306, 1056, 'ON THE PHONE', 'Install the APK, allow notifications, then check foreground / background / lock-screen delivery.', 'blue');
await save('apk-build.svg', 'Build the test app, then verify it on the phone', 'Server credentials and Device / Worker Tokens do not belong in the APK.', 420, b);

await fs.writeFile(path.join(out, 'diagram_manifest.json'), JSON.stringify({ generatedBy: 'build_diagrams.mjs', diagrams }, null, 2) + '\n');
console.log(JSON.stringify({ generated: diagrams.length, directory: out }));
