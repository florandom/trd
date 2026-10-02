import stylexPlugin from '@stylexswc/nextjs-plugin';
import {fileURLToPath} from 'node:url';

export default stylexPlugin({
  rsOptions: {unstable_moduleResolution: {type: 'commonJS'}},
})({
  output: 'standalone',
  outputFileTracingRoot: fileURLToPath(new URL('../../', import.meta.url)),
  transpilePackages: ['@trd/shared-types'],
  poweredByHeader: false,
  async headers() {
    return [{
      source: '/:path*',
      headers: [
        {key: 'X-Content-Type-Options', value: 'nosniff'},
        {key: 'Referrer-Policy', value: 'same-origin'},
        {key: 'X-Frame-Options', value: 'DENY'},
        {key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()'},
      ],
    }];
  },
});
