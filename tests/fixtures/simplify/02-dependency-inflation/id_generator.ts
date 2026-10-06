import { v4 as uuidv4 } from "uuid";
import cloneDeep from "lodash.clonedeep";

export function generateIdAndClone(data: any): { id: string; copy: any } {
    return {
        id: uuidv4(),
        copy: cloneDeep(data),
    };
}
