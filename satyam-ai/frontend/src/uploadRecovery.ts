export interface SavedUpload {
  uploadId: string;
  userId: string;
  fileName: string;
  fileSize: number;
  fileType: string;
  sha256: string;
  confirmedChunks: number[];
  updatedAt: number;
}

const DATABASE = "satyam-upload-recovery";
const STORE = "sessions";

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: "uploadId" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Could not open browser upload recovery storage."));
    request.onblocked = () => reject(new Error("Browser upload recovery storage is blocked by another tab."));
  });
}

async function execute<T>(operation: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE, "readwrite");
    const request = operation(transaction.objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Could not update browser upload recovery storage."));
    transaction.onabort = () => reject(transaction.error ?? new Error("Browser upload recovery transaction was aborted."));
    transaction.oncomplete = () => database.close();
    transaction.onerror = () => database.close();
  });
}

export async function saveRecovery(upload: SavedUpload) {
  await execute((store) => store.put(upload));
}

export async function listRecovery(userId: string): Promise<SavedUpload[]> {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE, "readonly");
    const request = transaction.objectStore(STORE).getAll();
    request.onsuccess = () => resolve((request.result as SavedUpload[]).filter((item) => item.userId === userId));
    request.onerror = () => reject(request.error ?? new Error("Could not load saved upload sessions."));
    transaction.onabort = () => reject(transaction.error ?? new Error("Browser upload recovery transaction was aborted."));
    transaction.oncomplete = () => database.close();
    transaction.onerror = () => database.close();
  });
}

export async function removeRecovery(uploadId: string) {
  await execute((store) => store.delete(uploadId));
}
