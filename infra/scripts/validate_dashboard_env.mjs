import {deployment} from '../../apps/dashboard/src/lib/deployment.ts';

try {
  const config = deployment();
  if (!config.remote) throw new Error('Remote configuration required');
  console.log('Configurazione della dashboard remota verificata.');
} catch {
  console.error('Configurazione Vercel incompleta o ambiente non compatibile. Consultare la guida di distribuzione.');
  process.exitCode = 1;
}
