---
description: Analyze PDF, Excel, Word, images and other files with deep insights
argument-hint: [file-path] [analysis-question]
allowed-tools: Read, Bash
disable-model-invocation: true
---

# File Analysis Command

Analyze various file types and provide deep insights.

## Supported File Types:
- **PDF** (.pdf) - Extract text, analyze structure, answer questions
- **Excel** (.xlsx, .xls) - Extract formulas, analyze data, statistics
- **Word** (.docx) - Extract text and formatting
- **Images** (.png, .jpg, .jpeg, .gif, .webp) - Describe content, extract text (OCR if available)
- **CSV** (.csv) - Data analysis and statistics
- **JSON** (.json) - Structure analysis and validation

## User Request:
- File path: $1
- Analysis question: $2

## Instructions:

### Step 1: Identify File Type
Check the file extension to determine the analysis approach.

### Step 2: Process Excel Files (.xlsx, .xls)

**IMPORTANT: You have THREE powerful options for Excel analysis:**

#### Option 1: Quick CLI Analysis (Fastest - Recommended for developers)
```bash
# Use an Excel-analyzer CLI tool of your choice.
# Configure its path via the $EXCEL_ANALYZER env var (no default — set it per project).
ANALYZER="${EXCEL_ANALYZER:?Set EXCEL_ANALYZER to your analyzer CLI path}"

node "$ANALYZER" "$1"

# For specific analysis:
node "$ANALYZER" "$1" --formulas  # Extract all formulas
node "$ANALYZER" "$1" --all       # Analyze all sheets
node "$ANALYZER" "$1" --sheet "SheetName"  # Specific sheet
node "$ANALYZER" "$1" --export output.json  # Export to JSON
```

**Benefits:**
- ✅ Instant results in terminal
- ✅ Professional-grade formula extraction
- ✅ Perfect for automation and scripts
- ✅ Supports batch processing
- ✅ Designed for financial modeling

#### Option 2: Interactive Web Analyzer (Best for visualization)
```
Build a standalone HTML Excel analyzer (e.g. via /quick-prototype).

This creates a standalone HTML file with:
- Drag-and-drop file upload
- Beautiful charts (Recharts)
- Statistical analysis (Math.js)
- Formula extraction and display
- Export capabilities
```

**Benefits:**
- ✅ Visual and interactive
- ✅ Browser-based (no installation)
- ✅ Easy to share with non-technical users
- ✅ Real-time data visualization

#### Option 3: AI-Powered Analysis (Best for insights)
```
Create a Python script using Anthropic API to:
- Understand complex Excel models
- Answer questions about the data
- Provide business insights
- Explain formula logic
```

**Recommendation Logic:**
- User asks "what formulas?" → Option 1 (CLI)
- User wants to "visualize" → Option 2 (Web)
- User asks "what does this mean?" → Option 3 (AI)
- User is a developer → Option 1 (CLI)
- User is non-technical → Option 2 (Web)

### Step 3: Process PDF Files
```bash
# If pdftotext is available
pdftotext "$1" - | head -100

# Or suggest:
"For detailed PDF analysis, I can:"
1. Extract and summarize text content
2. Analyze document structure
3. Answer specific questions about the content
4. Extract tables and data (if structured)

Note: For best results with complex PDFs, consider using the Anthropic API
with document support (available through Python/Node.js SDK).
```

### Step 4: Process Images
```bash
# Check if the image exists
file "$1"

# Suggest:
"For image analysis, I can:"
1. Describe the visual content
2. Extract text (if it contains text/diagrams)
3. Analyze charts and graphs
4. Identify objects and scenes

Note: Image analysis requires the Anthropic API.
Would you like me to create a Python script that can analyze this image?
```

### Step 5: Process CSV Files
```bash
# Quick preview
head -20 "$1"

# Offer to create analyzer
"I can analyze this CSV file. Would you like me to:"
1. Show statistical summary
2. Create an interactive visualization tool
3. Find patterns and correlations
4. Export analyzed results

I can create a React-based CSV analyzer using: /artifact-react
```

### Step 6: Process Word Documents (.docx)
```bash
# Suggest analysis approach
"For Word document analysis, I can:"
1. Extract text content
2. Preserve formatting information
3. Analyze document structure
4. Answer questions about the content

Note: This requires additional tools. Would you like me to:
- Create a simple text extraction script?
- Build an interactive document viewer?
```

## Quick File Info Helper

Always start by providing basic file information:

```bash
# File stats
ls -lh "$1"

# File type
file "$1"

# For text-based files, show preview
if file "$1" | grep -q "text"; then
    echo "Preview (first 20 lines):"
    head -20 "$1"
fi
```

## Example Responses:

**For Excel:**
"I found an Excel file with X sheets and Y formulas.
For comprehensive analysis, I can build an interactive HTML analyzer (e.g. via /quick-prototype).
Or I can provide quick statistics now."

**For PDF:**
"This PDF has X pages.
I can extract and analyze the text content.
What specific information are you looking for?"

**For Images:**
"I can analyze this image using the Anthropic API.
Should I create a Python script to:"
1. Describe the image content
2. Extract any text present
3. Analyze charts/diagrams

**For CSV:**
"CSV file with X rows and Y columns detected.
Would you like me to create an interactive analyzer?"

## Usage Examples:
- `/file-analyze data.xlsx "What formulas are used?"`
- `/file-analyze report.pdf "Summarize the key findings"`
- `/file-analyze chart.png "What does this graph show?"`
- `/file-analyze data.csv "Show me statistics"`

## Advanced: Create Analysis Scripts

If the user wants programmatic analysis, offer to create:

1. **Python script** for PDF/Image/Excel analysis using Anthropic API
2. **React app** for interactive file viewing
3. **Node.js script** for batch file processing

Always provide the most practical solution based on available tools and user needs!
