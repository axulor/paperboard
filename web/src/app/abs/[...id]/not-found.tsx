export default function PaperNotFound() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10 leading-7">
      <h1 className="text-3xl font-bold">arXiv 上没有这篇论文</h1>
      <p className="mt-4">
        网址里的编号要和 arXiv 的一样，例如 <code>/abs/2401.04088</code>
        ；旧式编号带斜杠，例如 <code>/abs/hep-th/9901001</code>。
      </p>
    </main>
  );
}
