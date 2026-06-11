import { redirect } from "next/navigation";

export default function RemovedOnlineChatPage() {
  redirect("/chat/local");
}
