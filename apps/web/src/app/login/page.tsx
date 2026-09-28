import Link from "next/link";
import { redirect } from "next/navigation";
import { defaultLocale, getMessages } from "@/i18n/messages";
import { LoginForm } from "@/features/auth/LoginForm";
import { getSessionUser } from "@/lib/auth";

/** Página de acceso real contra el BFF; con sesión activa redirige al panel. */
export default async function LoginPage(): Promise<React.JSX.Element> {
  const sessionUser = await getSessionUser();
  if (sessionUser !== null) redirect("/panel");

  const messages = getMessages(defaultLocale);
  const login = messages.login;

  return (
    <section aria-labelledby="titulo-acceso" className="mx-auto flex max-w-md flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 id="titulo-acceso" className="text-3xl font-bold tracking-tight">
          {login.title}
        </h1>
        <p className="text-ink/80">{login.subtitle}</p>
      </div>

      <LoginForm messages={messages} />

      <p className="text-sm text-ink/80">
        {login.noAccount}{" "}
        <Link href="/registro" className="font-semibold text-brand-800 underline underline-offset-4 hover:text-brand-700">
          {login.registerLink}
        </Link>
      </p>
      <p>
        <Link href="/" className="text-sm font-semibold text-brand-800 underline underline-offset-4 hover:text-brand-700">
          {login.backHome}
        </Link>
      </p>
    </section>
  );
}
