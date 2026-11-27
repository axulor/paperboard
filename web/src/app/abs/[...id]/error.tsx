"use client";

export default function PaperError({
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10 leading-7">
      <h1 className="text-3xl font-bold">暂时取不到这篇论文的数据</h1>
      <p className="mt-4">
        arXiv 或 PaperBoard 的服务暂时没有响应，请过一会儿再试。
      </p>
      <button className="mt-6 rounded border px-4 py-2" onClick={() => retry()}>
        再试一次
      </button>
    </main>
  );
}
