import Link from "next/link";
import { defaultLocale, getMessages } from "@/i18n/messages";
import { buttonClasses } from "@/components/ui";

/** Página 404 propia, en español. */
export default function NotFound(): React.JSX.Element {
  const messages = getMessages(defaultLocale);
  const notFound = messages.notFound;

  return (
    <section aria-labelledby="titulo-404" className="mx-auto flex max-w-md flex-col items-start gap-4">
      <h1 id="titulo-404" className="text-3xl font-bold tracking-tight">
        {notFound.title}
      </h1>
      <p className="text-ink/80">{notFound.description}</p>
      <div className="flex flex-wrap gap-3">
        <Link href="/" className={buttonClasses("primary", "md")}>
          {notFound.backHome}
        </Link>
        <Link href="/login" className={buttonClasses("secondary", "md")}>
          {notFound.loginLink}
        </Link>
      </div>
    </section>
  );
}
