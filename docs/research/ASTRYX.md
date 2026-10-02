# Astryx compatibility research and disposable spike

Research date: 2026-10-02. Phase 0 only. The temporary spike lives at `/private/tmp/trd-phase0-astryx.EGHJyl`; no frontend application was scaffolded in the repository. This note records package inspection, genuine CLI output and production-build checks. It does not claim visual, accessibility, browser-interaction or application acceptance testing.

## Decision

Astryx is feasible with the selected Next.js/React stack. Prefer published, precompiled components, the neutral prebuilt theme and CSS custom properties for the first dashboard. Import components from their documented category entrypoints. Use the theme's `/built` export together with `theme.css` for static production themes, so component overrides are present during server rendering.

Authored `stylex.create()` overrides require a compiler. A small override passed through Astryx's `xstyle` prop compiled successfully using the community SWC plugin and an explicit Next.js Webpack build. This is a verified path, with a third-party compiler dependency. Do not assume that the plugin's default export works with Next.js's default Turbopack build: its documentation requires a separate Turbopack export and PostCSS extraction plugin for that path, which was not tested here.

## Exact tested versions

| Dependency | Installed version |
|---|---|
| Node.js | 24.20.0 |
| `next` | 16.3.8 |
| `react`, `react-dom` | 19.3.0 |
| `@astryxdesign/core` | 0.6.4 |
| `@astryxdesign/cli` | 0.6.4 |
| `@astryxdesign/theme-neutral` | 0.6.4 |
| `@stylexjs/stylex` | 0.19.0 |
| `@stylexswc/nextjs-plugin` | 0.19.0 |
| `typescript` | 7.0.2 |
| `@types/react`, `@types/react-dom` | 19.3.0 |
| `@types/node` | 26.6.4 |

These are an observed compatibility set, not a claim that every latest version is required. Inspect package versions again when Phase 1 starts, then pin the chosen versions and preserve the lockfile. Astryx core declares React >=19 and StyleX ^0.19.0 peer dependencies; its CLI declares Node >=22.13.0. The CLI was invoked with an explicit Node 24.20.0 executable because another shell context resolved an older Node runtime. Version checks must use the same runtime as builds.

Dependencies were installed only in the temporary directory with `--ignore-scripts`. A first network-restricted installation stalled; the approved network installation completed. No production installation policy is inferred from that disposable-spike choice.

## CLI evidence and supported APIs

The installed CLI returned `0.6.4` for `--version`. These commands executed successfully against that exact package:

```text
astryx docs getting-started --full
astryx docs styling --full
astryx docs theme --full
astryx build themes
astryx template ThemeApply
astryx template dashboard
astryx template settings-sidebar
astryx component Button
astryx component Theme
astryx component AppShell
astryx component SideNav
astryx component Table
astryx component AlertDialog
```

The root research also inspected template listing, dashboard discovery and settings build guidance. Template source is a starting point: dashboard examples import chart/icon packages and use sample data, so copying a page does not establish functional trading behavior or remove those dependency requirements.

| UI responsibility | Verified import and contract |
|---|---|
| Dashboard frame | `AppShell` from `@astryxdesign/core/AppShell`; supports `topNav`, `sideNav`, `banner`, `mobileNav`, main `children`, `contentPadding`, and `height='fill'|'auto'`. |
| Navigation | `SideNav` from `@astryxdesign/core/SideNav`; supports `header`, children, footer slots, controlled collapse and resize configuration. Use router links and documented child components. |
| Data tables | `Table` from `@astryxdesign/core/Table`; data-driven `data`, typed `columns`, stable `idKey`, density and pagination accessibility counts. Column width uses exported `pixel()` or `proportional()` helpers, not a bare number. |
| Risk/control confirmation | `AlertDialog` from `@astryxdesign/core/AlertDialog`; required `isOpen`, `onOpenChange`, `title`, `description`, `actionLabel`, `onAction`. `onAction` does not automatically close the dialog. A UI confirmation does not substitute for server authorization or risk checks. |
| Theme | `Theme` from `@astryxdesign/core/theme`; required `theme`, children; optional mode `light`, `dark`, or `system`. Import `neutralTheme` from `@astryxdesign/theme-neutral/built`. |
| Actions | `Button` from `@astryxdesign/core/Button`; required accessible `label`; async `clickAction` or normal `onClick`, loading/disabled state and documented variants. |

Do not invent a generic UI package barrel, undocumented component names, or inline-object `xstyle`. CLI guidance states that `xstyle` values must come from `stylex.create()`. Standard external CSS belongs in `className`; public semantic theme tokens are the shared styling surface. New selectors should use stable component classes and reflected data attributes rather than deprecated bare prop classes.

## Build proof

### Published components and prebuilt theme

The minimal spike imported the documented reset, component CSS and neutral theme stylesheet:

```css
@import '@astryxdesign/core/reset.css';
@import '@astryxdesign/core/astryx.css';
@import '@astryxdesign/theme-neutral/theme.css';
```

A client page rendered `Theme theme={neutralTheme}`, Card, VStack, Heading, Text and Button using documented entrypoints. The uncustomized `next.config.mjs` exported an empty object. `next build` used Next 16.3.8's default Turbopack and exited 0: compilation succeeded, TypeScript finished, and `/` plus `/_not-found` were prerendered. Published Astryx components required no additional StyleX transform.

### Authored StyleX override

The second build added the compiler's documented default export to `next.config.mjs` and imported its Webpack carrier stylesheet in the root layout:

```js
import stylexPlugin from '@stylexswc/nextjs-plugin';

export default stylexPlugin({
  rsOptions: {unstable_moduleResolution: {type: 'commonJS'}},
})({});
```

```tsx
import '@stylexswc/webpack-plugin/stylex.css';
```

The button received `xstyle` from `stylex.create({action: {alignSelf: 'flex-end', marginTop: 'var(--spacing-4)'}})`. `next build --webpack` exited 0: compilation, TypeScript and prerendering succeeded. Generated static CSS contained `align-self:flex-end` and `margin-top:var(--spacing-4)`, and prerendered HTML carried the generated override classes on the actual Astryx button. This verifies emitted CSS and server markup, not a browser's measured layout or a click test. The compiler disables `experimental.webpackBuildWorker`; account for that when selecting the build configuration.

## Documentation discrepancy and remaining checks

Installed Astryx 0.6.4 styling guidance recommends the community SWC plugin to preserve Next's SWC/`next/font` path and points to `apps/example-nextjs-stylex`. The repository's referenced example currently declares Next ^15.5.21 and Babel/PostCSS packages, with an empty Next config. The example therefore does not establish Next 16 compatibility or the stated SWC configuration. The local spike above independently verifies a small Webpack/SWC path; no `next/font` use was tested.

The community plugin describes itself as independent of Meta, supports Next 15+, and identifies its default export as Webpack integration. Its Turbopack path needs its `/turbopack` export plus `@stylexswc/postcss-plugin`. Future scaffold work must choose one supported bundler path explicitly and verify generated styles rather than treating a successful JavaScript compilation alone as sufficient.

Before accepting the real frontend: verify browser rendering in light/dark mode, first paint and hydration; interactions and routing; mobile AppShell behavior; keyboard/focus behavior of tables/dialogs; stale-data and loading/error states; chart integration; and the exact project's CI production build. Theme font loading remains an explicit application concern. For custom static themes, use `astryx theme build` and ship the generated CSS, JS and declarations together; runtime theme injection is for prototypes or dynamic themes.

## Primary references

- [Astryx source and package documentation](https://github.com/facebook/astryx); exact installed 0.6.4 CLI docs and package manifests provide the version-specific evidence above.
- [Astryx Next.js example](https://github.com/facebook/astryx/tree/main/apps/example-nextjs).
- [Astryx Next.js + StyleX example](https://github.com/facebook/astryx/tree/main/apps/example-nextjs-stylex), including [its package manifest](https://github.com/facebook/astryx/blob/main/apps/example-nextjs-stylex/package.json) and [Next config](https://github.com/facebook/astryx/blob/main/apps/example-nextjs-stylex/next.config.mjs).
- [Community StyleX SWC compiler and Next.js integration](https://github.com/Dwlad90/stylex-swc-plugin); installed `@stylexswc/nextjs-plugin@0.19.0` README was also inspected for the build path and bundler distinction.
- [StyleX documentation](https://stylexjs.com/).

No Astryx dependency or tooling blocker was found for Phase 1. Authoring custom StyleX under default Turbopack remains a separate, untested setup choice; starting with the published CSS and prebuilt theme avoids requiring that choice for initial UI scaffolding.
