import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { aiArchitecture } from './build_mechanisms.mjs';
import { systemArchitecture } from './build_system_architecture.mjs';

export { aiArchitecture, systemArchitecture };
export async function buildArchitectures() {
  await fs.writeFile(new URL('ai-pipelines.svg', import.meta.url), aiArchitecture());
  await fs.writeFile(new URL('../pauseable-system.svg', import.meta.url), systemArchitecture());
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await buildArchitectures();
  console.log('Generated AI and system architecture diagrams.');
}
