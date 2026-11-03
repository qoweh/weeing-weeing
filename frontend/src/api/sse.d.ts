export function readChatStream(response: Response, options?: { onEvent?: (event: any) => void | Promise<void>; signal?: AbortSignal }): Promise<any>
