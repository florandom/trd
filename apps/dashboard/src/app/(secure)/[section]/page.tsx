import {notFound} from 'next/navigation';
import OperationalPage from '@/components/operational-page';
export default async function Page({
  params,
}: {
  params: Promise<{section: string}>;
}) {
  const {section} = await params;
  if (
    ![
      'settings',
      'risk',
      'agents',
      'models',
      'audit',
      'status',
      'positions',
      'signals',
      'sources',
      'telegram-messages',
      'costs',
    ].includes(section)
  )
    notFound();
  return <OperationalPage key={section} section={section} />;
}
