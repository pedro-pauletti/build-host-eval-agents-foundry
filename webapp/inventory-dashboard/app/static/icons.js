/* Zava Console — inline SVG icon set (no CDN, works offline / in-container).
   Hand-drawn 24x24 stroke icons in the Lucide visual style. */
const ICON_PATHS = {
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><path d="M12 18v4"/><path d="M8.5 22h7"/>',
  micOff: '<path d="M2 2l20 20"/><path d="M15 9.3V5a3 3 0 0 0-5.9-.7"/><path d="M9 9v2a3 3 0 0 0 4.6 2.5"/><path d="M5 10v1a7 7 0 0 0 10.7 6"/><path d="M19 11v-1"/><path d="M12 18v4"/><path d="M8.5 22h7"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4.2A1.2 1.2 0 0 1 9.2 3h5.6A1.2 1.2 0 0 1 16 4.2V6"/><path d="M18.5 6l-.9 13.1a2 2 0 0 1-2 1.9H8.4a2 2 0 0 1-2-1.9L5.5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
  send: '<path d="M12 19.5V5"/><path d="M5.5 11.5 12 5l6.5 6.5"/>',
  box: '<path d="M21 8.2 12 3.2 3 8.2v7.6l9 5 9-5V8.2z"/><path d="M3.3 7.7 12 12.6l8.7-4.9"/><path d="M12 22V12.6"/>',
  truck: '<path d="M3 16.5V6.4A1.4 1.4 0 0 1 4.4 5h9.2A1.4 1.4 0 0 1 15 6.4v10.1"/><path d="M15 9h3.4a1.4 1.4 0 0 1 1.1.6l2.2 3a1.4 1.4 0 0 1 .3.9v3"/><circle cx="7.5" cy="17.5" r="2.2"/><circle cx="17.5" cy="17.5" r="2.2"/><path d="M9.7 17.5h5.6"/><path d="M3 16.5h2.3"/><path d="M22 16.5h-2.3"/>',
  workflow: '<rect x="3" y="3" width="7.5" height="6.5" rx="1.6"/><rect x="13.5" y="14.5" width="7.5" height="6.5" rx="1.6"/><path d="M6.75 9.5v3.3a2.2 2.2 0 0 0 2.2 2.2h4.55"/>',
  calendar: '<rect x="3" y="4.8" width="18" height="16.7" rx="2.2"/><path d="M8 2.5v4"/><path d="M16 2.5v4"/><path d="M3 10.2h18"/><path d="M8 14h2"/><path d="M14 14h2"/>',
  pin: '<path d="M20 10.2c0 5.4-8 11.8-8 11.8s-8-6.4-8-11.8a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="2.9"/>',
  user: '<path d="M20 21v-1.8a4.2 4.2 0 0 0-4.2-4.2H8.2A4.2 4.2 0 0 0 4 19.2V21"/><circle cx="12" cy="7.4" r="4.2"/>',
  warn: '<path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9.2v4.3"/><path d="M12 17.2h.01"/>',
  sparkles: '<path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"/><path d="m18.8 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z"/>',
  brain: '<path d="M9.5 3.2A2.7 2.7 0 0 0 6.8 6a2.6 2.6 0 0 0-1.9 4.2A2.8 2.8 0 0 0 5 15.1a2.7 2.7 0 0 0 2.3 3.6A2.6 2.6 0 0 0 12 18V5.7a2.5 2.5 0 0 0-2.5-2.5z"/><path d="M14.5 3.2A2.7 2.7 0 0 1 17.2 6a2.6 2.6 0 0 1 1.9 4.2 2.8 2.8 0 0 1 .1 4.9 2.7 2.7 0 0 1-2.3 3.6A2.6 2.6 0 0 1 12 18"/><path d="M8.4 9.6h1.4"/><path d="M14.2 9.6h1.4"/><path d="M8.9 14h1.3"/><path d="M13.8 14h1.3"/>',
  activity: '<path d="M22 12h-3.6l-2.7 8-5.4-16-2.7 8H2"/>',
  check: '<path d="M20 6.5 9.2 17.3 4 12.1"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.3l3.2 1.9"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  checklist: '<path d="M3.5 6.2 5 7.7l2.8-2.9"/><path d="M3.5 12.2 5 13.7l2.8-2.9"/><path d="M3.5 18.2 5 19.7l2.8-2.9"/><path d="M11.5 6.5h9"/><path d="M11.5 12.5h9"/><path d="M11.5 18.5h9"/>',
  database: '<ellipse cx="12" cy="5.6" rx="8" ry="3.2"/><path d="M4 5.6v12.8c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2V5.6"/><path d="M4 12c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2"/>',
  book: '<path d="M12 7.4C10.5 5.9 8.5 5.1 4 5.1V18.9c4.5 0 6.5.8 8 2.3 1.5-1.5 3.5-2.3 8-2.3V5.1c-4.5 0-6.5.8-8 2.3z"/><path d="M12 7.4v13.8"/>',
  wrench: '<path d="M18.9 3.7a5 5 0 0 0-6.5 6.5l-7.9 7.9a2.15 2.15 0 0 0 3 3l7.9-7.9a5 5 0 0 0 6.5-6.5l-3 3-2.7-.8-.8-2.7 3.5-2.5z"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2.2"/><rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1"/><path d="M9.5 2v3"/><path d="M14.5 2v3"/><path d="M9.5 19v3"/><path d="M14.5 19v3"/><path d="M2 9.5h3"/><path d="M2 14.5h3"/><path d="M19 9.5h3"/><path d="M19 14.5h3"/>',
  layers: '<path d="m12 2.5 9 4.7-9 4.7-9-4.7 9-4.7z"/><path d="m3 12.2 9 4.7 9-4.7"/><path d="m3 16.9 9 4.6 9-4.6"/>',
  quote: '<path d="M9.2 6.5H5.8A2.8 2.8 0 0 0 3 9.3v1.9a2.8 2.8 0 0 0 2.8 2.8h1.5c0 2.2-1.1 3.4-3.3 4"/><path d="M20.2 6.5h-3.4A2.8 2.8 0 0 0 14 9.3v1.9a2.8 2.8 0 0 0 2.8 2.8h1.5c0 2.2-1.1 3.4-3.3 4"/>',
  hash: '<path d="M4 9h16"/><path d="M4 15h16"/><path d="M10 3.2 8 20.8"/><path d="M16 3.2 14 20.8"/>',
  zap: '<path d="M13 2.5 3.8 14h7l-.8 7.5L20.2 10h-7l.8-7.5z"/>',
  loop: '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6"/><path d="M20.8 3v5.2h-5.2"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2.4"/><path d="M14.5 4v16"/>',
  shield: '<path d="M12 21.6s7.7-3.8 7.7-9.7V5.3L12 2.4 4.3 5.3v6.6c0 5.9 7.7 9.7 7.7 9.7z"/><path d="m8.9 11.9 2.2 2.2 4-4.1"/>',
  code: '<path d="m16.2 17.8 5.6-5.8-5.6-5.8"/><path d="m7.8 6.2-5.6 5.8 5.6 5.8"/><path d="m13.8 4-3.6 16"/>',
  filter: '<path d="M3.5 4.5h17l-6.6 7.7v6.9l-3.8 1.9V12.2L3.5 4.5z"/>',
  play: '<path d="M7.5 4.7 19 12 7.5 19.3V4.7z"/>',
  broadcast: '<circle cx="12" cy="12" r="2.1"/><path d="M16.3 7.7a6 6 0 0 1 0 8.6"/><path d="M7.7 16.3a6 6 0 0 1 0-8.6"/><path d="M19.2 4.8a10 10 0 0 1 0 14.4"/><path d="M4.8 19.2a10 10 0 0 1 0-14.4"/>',
  bot: '<rect x="3" y="8" width="18" height="12.5" rx="3.2"/><path d="M12 8V5.2"/><circle cx="12" cy="3.6" r="1.5"/><path d="M8.6 13.2v1.6"/><path d="M15.4 13.2v1.6"/><path d="M9.8 17.4h4.4"/>',
  chart: '<path d="M3 3v16.5a1.5 1.5 0 0 0 1.5 1.5H21"/><path d="M8 17.5v-6"/><path d="M13 17.5V7"/><path d="M18 17.5v-3.5"/>',
  server: '<rect x="2.5" y="4" width="19" height="7" rx="2.2"/><rect x="2.5" y="13" width="19" height="7" rx="2.2"/><path d="M6.6 7.5h.01"/><path d="M6.6 16.5h.01"/><path d="M17.5 7.5h1.6"/><path d="M17.5 16.5h1.6"/>',
  search: '<circle cx="10.8" cy="10.8" r="7.3"/><path d="m21 21-5-5"/>',
  spark: '<path d="M12 2.8 13.6 9 20 12l-6.4 3L12 21.2 10.4 15 4 12l6.4-3L12 2.8z"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.2"/><path d="M15.5 8.5V5.7a2.2 2.2 0 0 0-2.2-2.2H5.7a2.2 2.2 0 0 0-2.2 2.2v7.6a2.2 2.2 0 0 0 2.2 2.2h2.8"/>',
  dot: '<circle cx="12" cy="12" r="4.5"/>',
  route: '<circle cx="5.5" cy="18.5" r="2.8"/><circle cx="18.5" cy="5.5" r="2.8"/><path d="M8.3 18.5h5.4a4 4 0 0 0 4-4V8.3"/>',
};

/** Return an inline SVG string for `name` (unknown names render a neutral dot). */
function ico(name, cls = '') {
  const body = ICON_PATHS[name] || ICON_PATHS.dot;
  return `<svg class="ico ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}
