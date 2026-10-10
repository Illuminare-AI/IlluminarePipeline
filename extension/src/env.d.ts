// The shared frontend module reads Vite's import.meta.env; the extension never calls that code path.
interface ImportMeta {
  readonly env: Record<string, string | undefined>;
}
