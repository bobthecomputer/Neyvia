-- Deterministic document-layout policies for Neyvia's managed DOCX profile.
--
-- Pandoc's default equal-width Word tables are a poor fit for matrices whose last
-- column contains only a small wave/status value.  Assigning explicit semantic
-- widths keeps identifiers and suite names readable without changing source data.

local function normalized_cell_text(cell)
  return pandoc.utils.stringify(cell):lower():gsub("%s+", " ")
end

local function header_names(table_element)
  if not table_element.head or not table_element.head.rows then
    return {}
  end
  local first_row = table_element.head.rows[1]
  if not first_row or not first_row.cells then
    return {}
  end
  local names = {}
  for index, cell in ipairs(first_row.cells) do
    names[index] = normalized_cell_text(cell)
  end
  return names
end

local function apply_widths(table_element, widths)
  local updated = {}
  for index, colspec in ipairs(table_element.colspecs) do
    updated[index] = {colspec[1], widths[index]}
  end
  table_element.colspecs = updated
  return table_element
end

function Table(table_element)
  local names = header_names(table_element)
  if #names == 4
      and names[1] == "pack"
      and names[2] == "capability ids"
      and names[3] == "primary suite"
      and names[4] == "wave" then
    return apply_widths(table_element, {0.18, 0.36, 0.34, 0.12})
  end
  if #names == 3
      and names[1] == "current execution maturity"
      and names[2] == "count"
      and names[3] == "meaning" then
    return apply_widths(table_element, {0.30, 0.10, 0.60})
  end
  return table_element
end
