import {notFound} from 'next/navigation';
import SignalDetail from '@/components/signal-detail';
export default async function Page({params}: {params: Promise<{id: string}>}) {
  const {id} = await params;
  if (!/^[a-f0-9-]{36}$/.test(id)) notFound();
  return <SignalDetail id={id} />;
}
