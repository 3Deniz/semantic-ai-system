import Image from "next/image";
import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-950 px-6 text-white">
      <div className="max-w-xl space-y-6 rounded-3xl border border-zinc-800 bg-zinc-900 p-10 text-center shadow-2xl">
        <Image
          className="mx-auto dark:invert"
          src="/next.svg"
          alt="Next.js logo"
          width={120}
          height={24}
          priority
        />
        <h1 className="text-4xl font-semibold tracking-tight">
          Semantic AI Decision Engine
        </h1>
        <p className="text-zinc-400">
          Open the live dashboard to inspect metrics, graph structure, and reasoning output.
        </p>
        <Link
          href="/dashboard"
          className="inline-flex h-12 items-center justify-center rounded-full bg-white px-6 font-medium text-zinc-950 transition-colors hover:bg-zinc-200"
        >
          Open dashboard
        </Link>
      </div>
    </main>
  );
}
