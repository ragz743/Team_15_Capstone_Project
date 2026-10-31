export type ConversationItem = {
  id: string;
  title: string;
  updated_at: string;
};

export type ConversationHistory = {
  conversations: ConversationItem[];
  selectedId: string | null;
  onSelect: (id: string) => void | Promise<void>;
  onRefresh: () => void | Promise<void>;
  onLoadOlder?: () => void | Promise<void>;
  onLoadEarlier?: () => void | Promise<void>;
};
