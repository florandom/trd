import TradingShell from '@/components/trading-shell';
import {requireSession} from '@/lib/session';
export default async function SecureLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <TradingShell user={await requireSession()}>{children}</TradingShell>;
}
