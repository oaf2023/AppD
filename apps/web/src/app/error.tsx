"use client";

import Link from "next/link";
import { defaultLocale, getMessages } from "@/i18n/messages";
import { Button, buttonClasses } from "@/components/ui";

type ErrorPageProps = {
  reset: () => void;
};

/** Página de error propia, en español, con reintento y vuelta al inicio. */
export default function ErrorPage({ reset }: ErrorPageProps): React.JSX.Element {
  const messages = getMessages(defaultLocale);
  const pageError = messages.pageError;

  return (
    <section aria-labelledby="titulo-error" className="mx-auto flex max-w-md flex-col items-start gap-4">
      <h1 id="titulo-error" className="text-3xl font-bold tracking-tight">
        {pageError.title}
      </h1>
      <p role="alert" className="text-ink/80">
        {pageError.description}
      </p>
      <div className="flex flex-wrap gap-3">
        <Button type="button" variant="primary" size="md" onClick={reset}>
          {pageError.retry}
        </Button>
        <Link href="/" className={buttonClasses("secondary", "md")}>
          {pageError.backHome}
        </Link>
      </div>
    </section>
  );
}
