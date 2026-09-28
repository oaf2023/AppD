import { defaultLocale, getMessages } from "@/i18n/messages";
import { Spinner } from "@/components/ui";

/** Estado de carga propio, en español y anunciado por lectores de pantalla. */
export default function Loading(): React.JSX.Element {
  const messages = getMessages(defaultLocale);
  return (
    <div className="mx-auto flex max-w-md items-center justify-center py-16">
      <Spinner label={messages.common.loading} visibleLabel />
    </div>
  );
}
