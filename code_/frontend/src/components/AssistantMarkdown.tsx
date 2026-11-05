import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  table: ({ children }) => (
    <div className="markdown-table-scroll" role="region" aria-label="Response table" tabIndex={0}>
      <table>{children}</table>
    </div>
  ),
};

export default function AssistantMarkdown({ text }: { text: string }) {
  return (
    <div className="assistant-markdown">
      <Markdown remarkPlugins={[remarkGfm]} components={components} skipHtml disallowedElements={["img"]}>
        {text}
      </Markdown>
    </div>
  );
}
