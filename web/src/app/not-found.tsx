export default function NotFound() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10 leading-7">
      <h1 className="text-3xl font-bold">没有这个页面</h1>
      <p className="mt-4">
        论文页的网址是 <code>/abs/</code> 加 arXiv 编号，例如{" "}
        <a className="underline" href="/abs/2401.04088">
          /abs/2401.04088
        </a>
        ；旧式编号带斜杠，例如 <code>/abs/hep-th/9901001</code>。
      </p>
    </main>
  );
}
