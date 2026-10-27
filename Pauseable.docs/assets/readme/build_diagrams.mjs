import fs from 'node:fs/promises';
import { buildMechanisms } from './build_mechanisms.mjs';
import { buildOverview } from './build_overview.mjs';
import { systemArchitecture } from './build_system_architecture.mjs';

const diagrams = await buildMechanisms();
await buildOverview();
await fs.writeFile(new URL('../pauseable-system.svg', import.meta.url), systemArchitecture());
diagrams.unshift({
  file: 'memolink-overview.svg',
  title: 'Memolink 동작 개요 · 개발팀 PAUSEABLE',
  kind: 'architecture', liveStatus: false,
  sources: ['README.md'],
});
await fs.writeFile(new URL('diagram_manifest.json', import.meta.url),
  JSON.stringify({ generatedBy: 'build_diagrams.mjs', diagrams }, null, 2) + '\n');
console.log(JSON.stringify({ generated: diagrams.length + 1, systemIncluded: true }));
