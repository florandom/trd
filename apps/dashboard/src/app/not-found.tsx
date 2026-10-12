// Adapted from Astryx EmptyStateActions inside the existing error-page frame.
'use client';

import Link from 'next/link';
import {Button} from '@astryxdesign/core/Button';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Section} from '@astryxdesign/core/Section';

export default function NotFoundPage() {
  return (
    <Section minHeight="100dvh" padding={6}>
      <EmptyState
        headingLevel={1} title="Pagina non trovata"
        description="La pagina richiesta non è disponibile. Torna alla panoramica per consultare lo stato dei servizi."
        actions={<Button label="Torna alla panoramica" variant="secondary" as={Link} href="/" />}
      />
    </Section>
  );
}
