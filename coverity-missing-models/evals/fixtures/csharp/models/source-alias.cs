// The same source, trying to keep the pass-through with an alias of the
// buffer. Reference.Alias is about closing, not taint: it does not restore it.
namespace System.IO
{
    public class MemoryStream
    {
        public MemoryStream(byte[] buffer)
        {
            Coverity.Primitives.Reference.Alias(this, buffer);
            Coverity.Primitives.Security.NetworkSource(this);
        }
    }
}
