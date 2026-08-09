/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MAX_SEED_TRACKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
