"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Spinner } from "@/components/ui";

type LogoutButtonProps = {
  label: string;
  busyLabel: string;
};

/** Botón de cierre de sesión (`POST /api/auth/logout` del BFF). */
export function LogoutButton({ label, busyLabel }: LogoutButtonProps): React.JSX.Element {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function handleClick(): Promise<void> {
    if (busy) return;
    setBusy(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Aunque falle la red, las cookies se borran en el servidor cuando es
      // posible; se redirige igualmente al acceso.
    } finally {
      setBusy(false);
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <Button type="button" variant="secondary" onClick={() => void handleClick()} disabled={busy}>
      {busy ? <Spinner label={busyLabel} /> : null}
      {busy ? busyLabel : label}
    </Button>
  );
}
