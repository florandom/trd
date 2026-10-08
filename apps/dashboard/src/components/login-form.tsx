// Adapted from Astryx 0.6.4 login: Center padding6, 400px column, Card padding8, gap4.
'use client';
import {useState} from 'react';
import {useRouter} from 'next/navigation';
import * as stylex from '@stylexjs/stylex';
import {VStack} from '@astryxdesign/core/Stack';
import {Center} from '@astryxdesign/core/Center';
import {Text, Heading} from '@astryxdesign/core/Text';
import {TextInput} from '@astryxdesign/core/TextInput';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {Banner} from '@astryxdesign/core/Banner';
import {Token} from '@astryxdesign/core/Token';
import {api} from '@/lib/dashboard-api';
const styles = stylex.create({
  page: {
    minHeight: '100dvh',
    backgroundColor: 'var(--color-background-body)',
  },
  column: {width: '100%', maxWidth: 400},
});

export default function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function signIn() {
    if (busy) return;
    if (!email || !password) {
      setError('Inserisci email e password.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const challenge = await api<{csrf_token: string}>('auth/csrf');
      await api('auth/login', {
        body: {email, password},
        csrf: challenge.csrf_token,
      });
      setPassword('');
      router.replace('/');
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Accesso non disponibile.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <Center axis="both" padding={6} xstyle={styles.page}>
      <VStack gap={4} hAlign="center" xstyle={styles.column}>
        <VStack gap={2} hAlign="center">
          <Text weight="bold" size="lg">
            TRD
          </Text>
          <Token label="SIMULAZIONE" color="blue" size="sm" />
        </VStack>
        <Card padding={8} width="100%">
          <VStack gap={4} hAlign="stretch">
            <VStack gap={1} hAlign="center">
              <Heading level={1}>Accedi</Heading>
              <Text color="secondary">
                Il tuo centro di controllo del trading.
              </Text>
            </VStack>
            {error && <Banner status="error" title={error} />}
            <TextInput
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              autoComplete="username"
              size="lg"
              onEnter={() => void signIn()}
              isReadOnly={busy}
            />
            <TextInput
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              size="lg"
              onEnter={() => void signIn()}
              isReadOnly={busy}
            />
            <Button
              label="Accedi"
              size="lg"
              isLoading={busy}
              onClick={() => void signIn()}
            />
            <Text type="supporting" color="secondary">
              Accesso riservato agli utenti autorizzati. Automazione e invio
              degli ordini disattivati.
            </Text>
          </VStack>
        </Card>
      </VStack>
    </Center>
  );
}
