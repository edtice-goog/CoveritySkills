// An attempt to add the throw the built-in model lacks. The null return is
// there to show the model applied (a NULL_RETURNS where the result is used),
// because nothing else shows it for a virtual method. The throw adds nothing:
// the handler stays unreachable.
namespace System.Resources
{
    public class ResourceManager
    {
        public virtual string GetString(string name)
        {
            if (Coverity.Primitives.Util.Nondet())
                throw new MissingManifestResourceException();
            return null;
        }
    }
}
