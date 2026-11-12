export type Message = {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
  turnId?: string;
  created_at?: string;
};

export type Conversation = {
  id: number;
  title: string;
  updated_at: string;
  message_count: number;
};

export type AgentTaskView = {
  id: string;
  state: string;
  changedFiles: string[];
  verificationStatus: string;
};

export type Approval = {
  approvalId: string;
  action: string;
  detail: string;
  diff: string;
  actionDigest: string;
  risk: "GREEN" | "AMBER" | "RED";
  purpose: string;
  resource: string;
  reversible: boolean;
  alternatives: string;
};

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  owner_project: string;
  embedding_model: string;
  embedding_dim: number;
  status: string;
  created_at: string;
  updated_at: string;
  document_count?: number;
  total_bytes?: number;
  total_chunks?: number;
};

export type KnowledgeDoc = {
  id: number;
  kb_id?: string;
  source_id?: number | null;
  file_path: string;
  title: string;
  content_hash: string;
  mime_type: string;
  size_bytes: number;
  chunk_count: number;
  indexed_at: string;
  status: "indexed" | "failed";
  error_message?: string | null;
  source_name?: string | null;
  chunks?: KnowledgeChunk[];
};

export type KnowledgeChunk = {
  id: number;
  document_id: number;
  chunk_index: number;
  content: string;
  token_count: number;
  start_line?: number;
  end_line?: number;
  page_number?: number;
  sheet_name?: string;
};

export type SearchResult = {
  citation_id: string;
  kb_id?: string;
  document_id: number;
  title: string;
  file_path: string;
  path?: string;
  chunk_index: number;
  start_line?: number;
  end_line?: number;
  page_number?: number;
  sheet_name?: string;
  snippet: string;
  content: string;
  score: number;
};

export type DatabaseConnector = {
  id: string;
  name: string;
  connector_type: string;
  config: Record<string, unknown>;
  is_read_only: boolean;
};

export type TableSchema = {
  name: string;
  type?: string;
  columns: { name: string; type: string; notnull?: boolean; pk?: boolean }[];
  row_count: number;
};

export type SchemaInspection = {
  database?: string;
  dataset_path?: string;
  table_count: number;
  tables: TableSchema[];
};

export type QueryResult = {
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  truncated: boolean;
};

export type AgentActivityEvent = {
  activity_id: string;
  action: string;
  risk: string;
  event: string;
  target: string;
  created_at: string;
};
