namespace QuantDashboard.Components;

public class SortState
{
    public string Column { get; private set; } = "";
    public bool Ascending { get; private set; } = true;

    public void Toggle(string col)
    {
        if (Column == col)
            Ascending = !Ascending;
        else
        {
            Column = col;
            Ascending = false; // 첫 클릭 = 내림차순
        }
    }

    public string Arrow(string col)
        => Column != col ? "" : Ascending ? " ▲" : " ▼";

    public IEnumerable<T> Apply<T>(IEnumerable<T> data,
        Dictionary<string, Func<T, object>> selectors)
    {
        if (string.IsNullOrEmpty(Column) || !selectors.ContainsKey(Column))
            return data;
        var sel = selectors[Column];
        return Ascending ? data.OrderBy(sel) : data.OrderByDescending(sel);
    }
}
