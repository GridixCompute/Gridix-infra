"use client";

import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useSession } from "@/lib/hooks/useSession";

export default function SettingsPage() {
  const { name, logout } = useSession();

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="font-[var(--font-display)] text-2xl font-bold text-[var(--color-ink)]">
        Settings
      </h1>

      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardBody className="space-y-1">
          <div className="text-sm text-[var(--color-ink-faint)]">Signed in as</div>
          <div className="font-[var(--font-display)] text-lg text-[var(--color-ink)]">
            {name ?? "Developer"}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>API key</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3 text-sm text-[var(--color-ink-soft)]">
          <p>
            Your key is stored in a secure httpOnly cookie and is never exposed to the browser. If
            it&apos;s compromised, register a new account to rotate it — key rotation on the same
            account is coming with the backend endpoint.
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Session</CardTitle>
        </CardHeader>
        <CardBody className="flex items-center justify-between">
          <span className="text-sm text-[var(--color-ink-faint)]">
            End this session on this device.
          </span>
          <Button variant="secondary" onClick={logout}>
            Sign out
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
