//@category ARELAB

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.Reference;
import java.io.File;
import java.io.FileWriter;
import java.io.Writer;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ExportFacts extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            throw new IllegalArgumentException("Expected output path");
        }

        File outFile = new File(args[0]);
        Listing listing = currentProgram.getListing();
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);

        List<Map<String, Object>> functions = new ArrayList<>();
        int count = 0;
        while (iterator.hasNext() && count < 128) {
            Function function = iterator.next();
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", function.getName());
            item.put("address", function.getEntryPoint().toString());

            String pseudocode = "";
            DecompileResults result = decompiler.decompileFunction(function, 30, monitor);
            if (result != null && result.decompileCompleted() && result.getDecompiledFunction() != null) {
                pseudocode = result.getDecompiledFunction().getC();
            }
            item.put("pseudocode", pseudocode);

            List<String> assembly = new ArrayList<>();
            InstructionIterator instructions = listing.getInstructions(function.getBody(), true);
            int seen = 0;
            while (instructions.hasNext() && seen < 25) {
                Instruction instruction = instructions.next();
                assembly.add(instruction.toString());
                seen += 1;
            }
            item.put("assembly_excerpt", String.join("\n", assembly));

            Reference[] refs = getReferencesTo(function.getEntryPoint());
            item.put("xref_count", refs.length);
            functions.add(item);
            count += 1;
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("program", currentProgram.getName());
        payload.put("language", currentProgram.getLanguageID().toString());
        payload.put("functions", functions);

        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        try (Writer writer = new FileWriter(outFile)) {
            gson.toJson(payload, writer);
        }
    }
}
