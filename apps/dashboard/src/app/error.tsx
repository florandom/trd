'use client';

import {Button} from '@astryxdesign/core/Button';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Section} from '@astryxdesign/core/Section';

export default function ErrorPage({reset}: {error: Error & {digest?: string}; reset: () => void}) {
  return (
    <Section minHeight="100dvh" padding={6}>
      <EmptyState
        headingLevel={1} title="Impossibile caricare la panoramica"
        description="Lo stato dei servizi non è disponibile. L’automazione è disattivata."
        actions={<Button label="Riprova" onClick={reset} />}
      />
    </Section>
  );
}
