import { redirect } from "next/navigation";

export default function LegacyChatPage() {
  redirect("/chat/local");
}
