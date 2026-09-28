import { redirect } from "next/navigation";
import { defaultLocale, getMessages } from "@/i18n/messages";
import { Badge, Card } from "@/components/ui";
import { LogoutButton } from "@/features/auth/LogoutButton";
import { getSessionUser } from "@/lib/auth";

/**
 * Panel protegido (Server Component): sin sesión redirige al acceso.
 * Muestra la cuenta real (`GET /api/v1/me`), el estado de la sesión y
 * bloques honestos sin datos inventados (mercados y operativa desactivada).
 */
export default async function PanelPage(): Promise<React.JSX.Element> {
  const user = await getSessionUser();
  if (user === null) redirect("/login");

  const messages = getMessages(defaultLocale);
  const panel = messages.panel;

  const rolesText = user.roles.length > 0 ? user.roles.join(", ") : panel.rolesEmpty;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-3xl font-bold tracking-tight">{panel.title}</h1>
          <p className="text-ink/80">{panel.subtitle}</p>
        </div>
        <LogoutButton label={panel.logout} busyLabel={panel.loggingOut} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title={panel.accountTitle}>
          <dl className="flex flex-col gap-2 text-sm">
            <div className="flex flex-col gap-0.5">
              <dt className="font-semibold text-ink">{panel.emailLabel}</dt>
              <dd className="text-ink/80">{user.email}</dd>
            </div>
            <div className="flex flex-col gap-0.5">
              <dt className="font-semibold text-ink">{panel.statusLabel}</dt>
              <dd className="text-ink/80">{user.status}</dd>
            </div>
            <div className="flex flex-col gap-0.5">
              <dt className="font-semibold text-ink">{panel.rolesLabel}</dt>
              <dd className="text-ink/80">{rolesText}</dd>
            </div>
            <div className="flex flex-col gap-0.5">
              <dt className="font-semibold text-ink">{panel.verifiedLabel}</dt>
              <dd className="text-ink/80">{user.email_verified ? panel.verifiedYes : panel.verifiedNo}</dd>
            </div>
            <div className="flex flex-col gap-0.5">
              <dt className="font-semibold text-ink">{panel.mfaLabel}</dt>
              <dd className="text-ink/80">{user.mfa_enabled ? panel.mfaYes : panel.mfaNo}</dd>
            </div>
          </dl>
        </Card>

        <div className="flex flex-col gap-4">
          <Card title={panel.sessionTitle}>
            <p className="text-sm text-ink/80">{panel.sessionActive}</p>
          </Card>
          <Card
            title={panel.marketsTitle}
            badge={<Badge tone="neutral">{messages.common.soonBadge}</Badge>}
          >
            <p className="text-sm text-ink/80">{panel.marketsText}</p>
          </Card>
        </div>
      </div>

      <Card
        title={panel.tradingTitle}
        badge={<Badge tone="danger">{messages.common.liveOffBadge}</Badge>}
      >
        <p className="text-sm text-ink/80">{panel.tradingText}</p>
      </Card>
    </div>
  );
}
