import Link from "next/link";
import { redirect } from "next/navigation";
import { defaultLocale, getMessages } from "@/i18n/messages";
import { RegisterForm } from "@/features/auth/RegisterForm";
import { getSessionUser } from "@/lib/auth";

/** Página de registro real contra el BFF; con sesión activa redirige al panel. */
export default async function RegisterPage(): Promise<React.JSX.Element> {
  const sessionUser = await getSessionUser();
  if (sessionUser !== null) redirect("/panel");

  const messages = getMessages(defaultLocale);
  const register = messages.register;

  return (
    <section aria-labelledby="titulo-registro" className="mx-auto flex max-w-md flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 id="titulo-registro" className="text-3xl font-bold tracking-tight">
          {register.title}
        </h1>
        <p className="text-ink/80">{register.subtitle}</p>
      </div>

      <RegisterForm messages={messages} />

      <p className="text-sm text-ink/80">
        {register.hasAccount}{" "}
        <Link href="/login" className="font-semibold text-brand-800 underline underline-offset-4 hover:text-brand-700">
          {register.loginLink}
        </Link>
      </p>
      <p>
        <Link
          href="/"
          className="text-sm font-semibold text-brand-800 underline underline-offset-4 hover:text-brand-700"
        >
          {register.backHome}
        </Link>
      </p>
    </section>
  );
}
