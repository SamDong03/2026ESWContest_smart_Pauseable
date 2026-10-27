import fs from 'node:fs';

const brands = JSON.parse(fs.readFileSync(new URL('./brand-icons.json', import.meta.url), 'utf8'));
export const W = 1440;
export const C = {
  ink: '#23382f', muted: '#52675d', line: '#768b81', light: '#dbe5df',
  green: '#2c684d', greenBg: '#edf5ec', greenLine: '#abc8b2',
  blue: '#356797', blueBg: '#edf3fb', blueLine: '#adc7e1',
  teal: '#087b7d', tealBg: '#eaf6f4', tealLine: '#a3ccc6',
  amber: '#916013', amberBg: '#fff6e3', amberLine: '#ddc795',
  red: '#9b4641', redBg: '#fff0ee', redLine: '#dfb3ad',
};
export const esc = value => String(value).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export function text(x, y, value, size = 18, fill = C.ink, weight = 400, width = W - x - 32) {
  return `<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${fill}" data-max-width="${width}">${esc(value)}</text>`;
}
export function rect(x, y, w, h, fill = '#fff', stroke = C.light, radius = 8) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="1.3"/>`;
}
export function logo(key, x, y, size = 26) {
  const list = brands.icons;
  const item = Array.isArray(list) ? list.find(i => i.slug === key || i.name === key) : list?.[key];
  if (!item) throw new Error(`Unknown brand: ${key}`);
  return `<g transform="translate(${x} ${y}) scale(${size / 24})" fill="#${item.hex}"><path d="${item.path}"/></g>`;
}
export function group(x, y, w, h, title, tone = 'green', brand = '') {
  return rect(x, y, w, h, C[`${tone}Bg`], C[`${tone}Line`], 12) +
    (brand ? logo(brand, x + 20, y + 18) : '') +
    text(x + (brand ? 58 : 20), y + 40, title, 23, C[tone], 700, w - (brand ? 78 : 40)) +
    `<path d="M${x} ${y + 58}H${x + w}" stroke="${C[`${tone}Line`]}"/>`;
}
export function box(x, y, w, h, title, lines = [], tone = 'green', dark = false) {
  return rect(x, y, w, h, dark ? C[tone] : '#fff', C[`${tone}Line`]) +
    text(x + 18, y + 33, title, 22, dark ? '#fff' : C.ink, 700, w - 36) +
    lines.map((line, i) => text(x + 18, y + 62 + i * 26, line, 18, dark ? '#eff7f2' : C.muted, 400, w - 36)).join('');
}
export function arrow(d, tone = 'green', dashed = false) {
  return `<path d="${d}" fill="none" stroke="${C[tone]}" stroke-width="2.2" stroke-linejoin="round" ${dashed ? 'stroke-dasharray="7 5"' : ''} marker-end="url(#arrow-${tone})"/>`;
}
export function note(x, y, w, title, detail, tone = 'blue') {
  return rect(x, y, w, 80, C[`${tone}Bg`], C[`${tone}Line`]) + text(x + 18, y + 29, title, 19, C[tone], 700, w - 36) + text(x + 18, y + 57, detail, 18, C.muted, 400, w - 36);
}
export function table(x, y, widths, headings, rows, tone = 'green', rowHeight = 56) {
  const width = widths.reduce((a, b) => a + b, 0);
  let result = rect(x, y, width, 48, C[tone], C[tone], 0);
  let at = x;
  headings.forEach((value, i) => { result += text(at + 16, y + 31, value, 19, '#fff', 700, widths[i] - 32); at += widths[i]; });
  rows.forEach((row, i) => {
    const top = y + 48 + i * rowHeight;
    result += rect(x, top, width, rowHeight, i % 2 ? '#f3f6f4' : '#fff', C.light, 0);
    let left = x;
    row.forEach((value, j) => {
      String(value).split('\n').forEach((line, k) => { result += text(left + 16, top + 31 + k * 24, line, 18, C.ink, j === 0 ? 700 : 400, widths[j] - 32); });
      left += widths[j];
    });
  });
  return result;
}
export function frame(title, subtitle, height, content) {
  const markers = ['green', 'blue', 'teal', 'amber', 'red'].map(t => `<marker id="arrow-${t}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="${C[t]}"/></marker>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${height}" viewBox="0 0 ${W} ${height}" role="img" aria-labelledby="title desc"><title id="title">${esc(title)}</title><desc id="desc">${esc(subtitle)}</desc><defs>${markers}</defs><rect width="${W}" height="${height}" fill="#fff"/><g font-family="'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', Arial, sans-serif">${text(32, 46, title, 32, C.ink, 700, 1040)}${text(1122, 43, 'Memolink / 개발팀 PAUSEABLE', 17, C.muted, 700, 286)}${text(32, 79, subtitle, 19, C.muted, 400, 1376)}<path d="M32 100H1408" stroke="${C.light}"/>${content}</g></svg>\n`;
}
