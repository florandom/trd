'use client';

import {Button} from '@astryxdesign/core/Button';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Section} from '@astryxdesign/core/Section';

export default function ErrorPage({reset}: {error: Error & {digest?: string}; reset: () => void}) {
  return (
    <Section minHeight="100dvh" padding={6}>
      <EmptyState
        headingLevel={1} title="The overview could not load"
        description="System readiness is unknown. Automation remains disabled in this foundation."
        actions={<Button label="Try again" onClick={reset} />}
      />
    </Section>
  );
}
