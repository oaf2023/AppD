import Link from "next/link";
import { defaultLocale, getMessages } from "@/i18n/messages";
import { LoginForm } from "@/features/auth/LoginForm";

/** Página de acceso (Fase 1): formulario en estado MOCK, sin backend. */
export default function LoginPage(): React.JSX.Element {
  const messages = getMessages(defaultLocale);
  const login = messages.login;

  return (
    <section aria-labelledby="titulo-acceso" className="mx-auto flex max-w-md flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 id="titulo-acceso" className="text-3xl font-bold">
          {login.title}
        </h1>
        <p>{login.subtitle}</p>
      </div>

      <LoginForm messages={login} />

      <Link href="/" className="text-sm text-brand-600 underline">
        {login.backHome}
      </Link>
    </section>
  );
}
