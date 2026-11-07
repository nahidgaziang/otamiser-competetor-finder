// @ts-check
import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

// https://astro.build/config
export default defineConfig({
  output: 'server',
  adapter: node({
    mode: 'standalone'
  }),
  vite: {
    envDir: '..'
  },
  security: {
    checkOrigin: true,
    allowedDomains: [
      { hostname: '127.0.0.1' },
      { hostname: 'localhost' }
    ]
  },
  server: {
    host: '127.0.0.1',
    port: 4321
  }
});

