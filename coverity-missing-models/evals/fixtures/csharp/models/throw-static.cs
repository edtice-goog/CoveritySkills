// The same attempt on a static method. The null return shows the model
// applied; the throw is compiled into the model and still adds nothing.
namespace System.IO
{
    public static class Path
    {
        public static string GetFileName(string path)
        {
            if (Coverity.Primitives.Util.Nondet())
                throw new InvalidOperationException();
            return null;
        }
    }
}
