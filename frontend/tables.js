// 表格列宽计算与拖拽：由入口显式注入依赖。
window.TableLayout = {
  create(deps) {
    const {
      document, getComputedStyle,
    } = deps;
    function balanceTableColumns(container) {
      const tables = container.querySelectorAll('table');
      const pageWidth = parseInt(getComputedStyle(document.getElementById('page')).getPropertyValue('--page-width').trim()) || 720;
      const availableWidth = pageWidth - 64;  // padding: 60px 32px → 32+32=64px horizontal

      for (const table of tables) {
        if (table.rows.length === 0) continue;
        const colCount = table.rows[0].cells.length;
        if (colCount === 0) continue;

        const colWidths = new Array(colCount).fill(0);
        for (let r = 0; r < table.rows.length; r++) {
          for (let c = 0; c < Math.min(table.rows[r].cells.length, colCount); c++) {
            const cell = table.rows[r].cells[c];
            const textLen = cell.textContent.replace(/\s+/g, ' ').length;
            const estWidth = Math.max(textLen * 8 + 28, 50);
            colWidths[c] = Math.max(colWidths[c], estWidth);
          }
        }

        let totalDesired = colWidths.reduce((a, b) => a + b, 0);
        const minColWidth = 60;
        const maxColWidth = Math.min(400, availableWidth * 0.6);

        if (totalDesired > availableWidth) {
          const ratio = availableWidth / totalDesired;
          for (let c = 0; c < colCount; c++) colWidths[c] = Math.max(minColWidth, Math.floor(colWidths[c] * ratio));
        } else if (totalDesired < availableWidth) {
          const extra = availableWidth - totalDesired;
          for (let c = 0; c < colCount; c++) colWidths[c] += Math.floor(extra * (colWidths[c] / totalDesired));
        }
        for (let c = 0; c < colCount; c++) colWidths[c] = Math.min(colWidths[c], maxColWidth);

        const currentTotal = colWidths.reduce((a, b) => a + b, 0);
        if (currentTotal < availableWidth) colWidths[colCount - 1] += availableWidth - currentTotal;
        else if (currentTotal > availableWidth) {
          colWidths[colCount - 1] -= currentTotal - availableWidth;
          if (colWidths[colCount - 1] < minColWidth) colWidths[colCount - 1] = minColWidth;
        }

        // Apply widths through a <colgroup> so columns stay independently
        // resizable. Tables that already carry a <colgroup> were balanced before
        // and may have been drag-resized by the user — never re-balance those
        // (it would silently reset drag-adjusted widths, e.g. after a paste).
        if (table.querySelector('colgroup')) continue;
        const total = colWidths.reduce((a, b) => a + b, 0);
        const colgroup = document.createElement('colgroup');
        table.insertBefore(colgroup, table.firstChild);
        colgroup.innerHTML = '';
        colWidths.forEach((w) => {
          const col = document.createElement('col');
          col.style.width = (w / total * 100).toFixed(2) + '%';
          colgroup.appendChild(col);
        });

        enableTableResize(table);
      }
    }

    // Allow dragging a column's right border to resize it; the space taken/given
    // is borrowed from the adjacent column so the table width stays constant.
    function setColumnEdge(table, colIndex, on) {
      for (let r = 0; r < table.rows.length; r++) {
        const cells = table.rows[r].cells;
        if (colIndex >= cells.length) continue;
        const cell = cells[colIndex];
        cell.classList.toggle('col-edge', on);
        cell.style.cursor = on ? 'col-resize' : '';
      }
    }
    function clearColumnEdges(table) {
      const all = table.querySelectorAll('th, td');
      for (const cell of all) {
        cell.classList.remove('col-edge');
        if (cell.style.cursor === 'col-resize') cell.style.cursor = '';
      }
    }

    function getResizeColumnFromEvent(table, e) {
      const EDGE = 6;
      const cell = e.target.closest('th, td');
      if (!cell || !table.contains(cell)) return -1;
      const cells = Array.from(cell.parentElement.cells);
      const i = cells.indexOf(cell);
      if (i < 0 || i >= cells.length - 1) return -1;
      const rect = cell.getBoundingClientRect();
      return e.clientX >= rect.right - EDGE && e.clientX <= rect.right + 2 ? i : -1;
    }

    function enableTableResize(table) {
      if (table.__resizeReady) return;
      table.__resizeReady = true;
      table.addEventListener('mousemove', (e) => {
        if (table.__dragging) return;
        const i = getResizeColumnFromEvent(table, e);
        clearColumnEdges(table);
        if (i >= 0) setColumnEdge(table, i, true);
      });
      table.addEventListener('mouseleave', () => {
        if (!table.__dragging) clearColumnEdges(table);
      });
      table.addEventListener('mousedown', (e) => {
        const i = getResizeColumnFromEvent(table, e);
        if (i < 0) return;
        e.preventDefault();
        startColDrag(table, i, e);
      });
    }

    function startColDrag(table, i, e) {
      const colgroup = table.querySelector('colgroup');
      if (!colgroup) return;
      const cols = Array.from(colgroup.querySelectorAll('col'));
      if (i + 1 >= cols.length) return;

      const headerCells = Array.from(table.rows[0].cells);
      const totalPx = table.getBoundingClientRect().width;
      const widthsPx = headerCells.map((c) => c.getBoundingClientRect().width);
      const startX = e.clientX;
      const minPx = 40;

      table.__dragging = true;
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'col-resize';

      const onMove = (ev) => {
        const deltaPx = ev.clientX - startX;
        let newCur = widthsPx[i] + deltaPx;
        let newNext = widthsPx[i + 1] - deltaPx;
        if (newCur < minPx) { newNext -= minPx - newCur; newCur = minPx; }
        if (newNext < minPx) { newCur -= minPx - newNext; newNext = minPx; }
        if (newCur < minPx) newCur = minPx;
        if (newNext < minPx) newNext = minPx;
        cols[i].style.width = (newCur / totalPx * 100).toFixed(2) + '%';
        cols[i + 1].style.width = (newNext / totalPx * 100).toFixed(2) + '%';
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        table.__dragging = false;
        Array.from(table.querySelectorAll('th, td')).forEach((c) => { c.classList.remove('col-edge'); c.style.cursor = ''; });
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    return {
      balanceTableColumns, setColumnEdge, clearColumnEdges, getResizeColumnFromEvent, enableTableResize, 
      startColDrag,
    };
  }
};
